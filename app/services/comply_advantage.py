"""
ComplyAdvantage Mesh API Client
https://docs.mesh.complyadvantage.com/reference/createtoken
"""
import time
import logging
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger("garudar_api")


class ComplyAdvantageClient:
    """Асинхронный HTTP-клиент для ComplyAdvantage Mesh API"""

    def __init__(self):
        self.base_url = settings.COMPLY_ADVANTAGE_BASE_URL.rstrip("/")
        self.realm = settings.COMPLY_ADVANTAGE_REALM
        self.username = settings.COMPLY_ADVANTAGE_USERNAME
        self.password = settings.COMPLY_ADVANTAGE_PASSWORD
        self.screening_config_id = settings.COMPLY_ADVANTAGE_SCREENING_CONFIG_ID
        self._token: Optional[str] = None
        self._token_expires_at: float = 0

    def _is_configured(self) -> bool:
        return bool(self.realm and self.username and self.password)

    async def _get_token(self) -> str:
        """Получить OAuth2 bearer token, кешировать на 23 часа"""
        if self._token and time.time() < self._token_expires_at:
            return self._token

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/v2/token",
                json={
                    "realm": self.realm,
                    "username": self.username,
                    "password": self.password,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        self._token = data["access_token"]
        expires_in = data.get("expires_in", 86400)
        self._token_expires_at = time.time() + expires_in - 3600  # обновляем за час до истечения
        return self._token

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Выполнить авторизованный запрос к API"""
        if not self._is_configured():
            raise RuntimeError("ComplyAdvantage API не настроен. Проверьте COMPLY_ADVANTAGE_* переменные в .env")

        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)

            # Retry на 401 (expired token)
            if resp.status_code == 401:
                self._token = None
                token = await self._get_token()
                headers["Authorization"] = f"Bearer {token}"
                resp = await client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)

            resp.raise_for_status()
            return resp.json()

    async def screen_person(
        self,
        external_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        full_name: Optional[str] = None,
        date_of_birth: Optional[dict] = None,
        nationality: Optional[list[str]] = None,
    ) -> dict:
        """Скрининг физического лица через create-and-screen workflow"""
        person = {}
        if first_name:
            person["first_name"] = first_name
        if last_name:
            person["last_name"] = last_name
        if full_name:
            person["full_name"] = full_name

        if date_of_birth:
            person["date_of_birth"] = date_of_birth
        if nationality:
            person["nationality"] = nationality
        customer: dict = {"external_identifier": external_id, "person": person}

        config = {"screening_configuration_identifier": self.screening_config_id} if self.screening_config_id else {}
        payload = {
            "customer": customer,
            "configuration": config,
            "monitoring": {"entity_screening": {"enabled": False}},
        }
        return await self._request("POST", "/v2/workflows/sync/create-and-screen?last_sync_step=ALERTING", json=payload)

    async def screen_company(
        self,
        external_id: str,
        legal_name: str,
        registration_number: Optional[str] = None,
        country: Optional[str] = None,
    ) -> dict:
        """Скрининг юридического лица"""
        company: dict = {"legal_name": legal_name}
        if registration_number:
            company["registration_authority_identification"] = registration_number
        if country:
            company["place_of_registration"] = country

        customer: dict = {"external_identifier": external_id, "company": company}

        config = {"screening_configuration_identifier": self.screening_config_id} if self.screening_config_id else {}
        payload = {
            "customer": customer,
            "configuration": config,
            "monitoring": {"entity_screening": {"enabled": False}},
        }
        return await self._request("POST", "/v2/workflows/sync/create-and-screen?last_sync_step=ALERTING", json=payload)

    async def get_customer(self, customer_identifier: str) -> dict:
        """Получить детали клиента"""
        return await self._request("GET", f"/v2/customers/{customer_identifier}")

    async def get_alert_risks(self, alert_identifier: str) -> dict:
        """Получить детали рисков по алерту (профили, aml_types, санкционные списки)"""
        return await self._request("GET", f"/v2/alerts/{alert_identifier}/risks")

    async def update_monitoring(self, customer_identifier: str, enabled: bool) -> dict:
        """Включить/выключить мониторинг"""
        body: dict = {"entity_screening": {"enabled": enabled}}
        if enabled and self.screening_config_id:
            body["entity_screening"]["configuration_identifier"] = self.screening_config_id
        return await self._request(
            "PATCH",
            f"/v2/customers/{customer_identifier}/monitoring",
            json=body,
        )

    async def register_webhook(self, url: str, event_type: str, name: str) -> dict:
        """Зарегистрировать webhook в ComplyAdvantage"""
        return await self._request("POST", "/v2/notifications/configurations/webhook", json={
            "is_active": True,
            "name": name,
            "type": event_type,
            "url": url,
        })

    async def list_webhooks(self) -> dict:
        """Список зарегистрированных webhooks"""
        return await self._request("GET", "/v2/notifications/configurations/webhook")

    async def update_and_rescore(self, customer_identifier: str, data: dict) -> dict:
        """Обновить данные клиента и пересчитать риск"""
        return await self._request(
            "POST",
            f"/v2/customers/{customer_identifier}/workflows/sync/update-and-rescore",
            json=data,
        )

    async def get_workflow(self, workflow_instance_identifier: str) -> dict:
        """Получить состояние workflow по идентификатору.
        GET /v2/workflows/{workflow_instance_identifier}
        """
        if not self._is_configured():
            raise RuntimeError("ComplyAdvantage не настроен")
        return await self._request("GET", f"/v2/workflows/{workflow_instance_identifier}")

    async def get_customer_cases(self, customer_identifier: str) -> list[dict]:
        """Получить кейсы клиента из CA.
        GET /v2/cases?customer_id={customer_identifier}&page_size=5
        Возвращает список объектов кейса или [] если нет / ошибка.
        """
        if not self._is_configured():
            raise RuntimeError("ComplyAdvantage не настроен")
        data = await self._request("GET", f"/v2/cases?customer_id={customer_identifier}&page_size=5")
        return data.get("data", [])

    async def add_case_note(self, case_identifier: str, note: str) -> dict:
        """Добавить заметку к кейсу в ComplyAdvantage.
        POST /v2/cases/{case_identifier}/notes
        Body: { "body": "..." }
        """
        if not self._is_configured():
            raise RuntimeError("ComplyAdvantage не настроен")
        return await self._request(
            "POST",
            f"/v2/cases/{case_identifier}/notes",
            json={"body": note},
        )

    async def get_customer_audit(
        self,
        customer_identifier: str,
        page_number: int = 1,
        page_size: int = 50,
        sort: str = "-occurred_at",
    ) -> dict:
        """Получить audit-trail клиента из CA.
        GET /v2/audit/customers/{customer_identifier}
        Возвращает page объекта audit_CustomerAuditLogsPageV2:
        { audit_logs: [...], first, next, prev, self, total_count }
        """
        if not self._is_configured():
            raise RuntimeError("ComplyAdvantage не настроен")
        params = {
            "page_number": page_number,
            "page_size": page_size,
            "sort": sort,
        }
        return await self._request(
            "GET",
            f"/v2/audit/customers/{customer_identifier}",
            params=params,
        )

    async def get_customer_scores(self, customer_identifier: str) -> dict:
        """Получить детальный risk-score клиента с разбивкой по категориям.
        GET /v2/customers/{customer_identifier}/scores

        Возвращает:
        {
            score_identifier, customer_identifier, customer_version,
            risk_model_identifier, risk_model_version, type,
            overall_result: { level, score },
            category_results: [{ category, score, weight, level, attribute_results: [...] }],
            created_at, updated_by
        }
        """
        if not self._is_configured():
            raise RuntimeError("ComplyAdvantage не настроен")
        return await self._request(
            "GET",
            f"/v2/customers/{customer_identifier}/scores",
        )

    async def rescreen_customer(
        self,
        customer_identifier: str,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Перескрин существующего клиента в CA с DELTA-режимом.
        POST /v2/customers/{customer_identifier}/workflows/sync/rescreen?rescreen_type=DELTA

        DELTA → алерты только на новые/изменившиеся риски (не дублируют старые hit'ы).
        idempotency_key (opt.) — `X-ComplyAdvantage-Idempotency-Key` header; safe для retry
        на сетевых ошибках без двойного списания квоты.

        Возвращает workflow-state с step_details (customer-rescreening, alerting).
        """
        if not self._is_configured():
            raise RuntimeError("ComplyAdvantage не настроен")
        headers = {}
        if idempotency_key:
            headers["X-ComplyAdvantage-Idempotency-Key"] = idempotency_key

        # _request не принимает extra headers напрямую — делаем inline-запрос с
        # тем же token-flow. Подробнее: _request использует `headers` локально,
        # здесь нам нужно добавить ещё один header к авторизации.
        token = await self._get_token()
        request_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            **headers,
        }
        url = f"{self.base_url}/v2/customers/{customer_identifier}/workflows/sync/rescreen?rescreen_type=DELTA"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=request_headers)
            if resp.status_code == 401:
                self._token = None
                token = await self._get_token()
                request_headers["Authorization"] = f"Bearer {token}"
                resp = await client.post(url, headers=request_headers)
            resp.raise_for_status()
            return resp.json()

    async def transition_alert(self, alert_identifier: str, state: str) -> dict:
        """Перевести alert в новое состояние в CA.
        POST /v2/alerts/{alert_identifier}/transition
        Body: { state: NOT_STARTED | IN_PROGRESS | POSITIVE_END_STATE | NEGATIVE_END_STATE }

        Mapping нашего workflow:
        - confirm (true positive) → POSITIVE_END_STATE
        - dismiss (false positive) → NEGATIVE_END_STATE
        """
        if not self._is_configured():
            raise RuntimeError("ComplyAdvantage не настроен")
        return await self._request(
            "POST",
            f"/v2/alerts/{alert_identifier}/transition",
            json={"state": state},
        )

    async def generate_customer_report(self, customer_identifier: str) -> dict:
        """Запросить screening-report (PDF) для клиента.
        POST /v2/customers/{customer_identifier}/reports
        Body: [{ "report_type": "SCREENING_REPORT" }]

        Возвращает cert_PaginatedResponseReport:
        {
            reports: [{ status: "READY"|"NOT_READY", download_url, expires_at, ... }]
        }
        - HTTP 201 + status READY → отчёт готов, download_url действителен.
        - HTTP 200 + status NOT_READY → ещё готовится, нужно повторить позже.
        CA возвращает ту же схему в обоих случаях, мы проверяем `status`.
        """
        if not self._is_configured():
            raise RuntimeError("ComplyAdvantage не настроен")
        return await self._request(
            "POST",
            f"/v2/customers/{customer_identifier}/reports",
            json=[{"report_type": "SCREENING_REPORT"}],
        )


# Singleton
comply_advantage_client = ComplyAdvantageClient()
