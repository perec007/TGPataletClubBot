"""
Скрапер страницы мониторинга метеостанций.
Авторизуется по логину/паролю и парсит данные о погоде.
Поддерживает Playwright для страниц с динамической загрузкой данных через JS.
"""
import re
import logging
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import MONITOR_URL, MONITOR_LOGIN, MONITOR_PASSWORD, USE_PLAYWRIGHT
from cache import get_cached_data, save_to_cache

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@dataclass
class WeatherData:
    """Структура данных о погоде с метеостанции."""
    temperature: Optional[float] = None      # °C
    wind_speed: Optional[float] = None       # м/с
    wind_gusts: Optional[float] = None       # м/с (порывы)
    wind_direction: Optional[float] = None   # градусы
    precipitation: Optional[float] = None    # мм
    humidity: Optional[float] = None         # %
    battery: Optional[float] = None          # Вольт (В)
    raw_text: str = ""
    timestamp: Optional[str] = None

    def to_text(self) -> str:
        """Форматирование данных для вывода в Telegram."""
        lines = ["📊 **Показания метеостанции аэродрома Паралёт:**"]
        if self.temperature is not None:
            lines.append(f"🌡 Температура: {self.temperature} °C")
        if self.wind_speed is not None:
            wind_str = f"💨 Скорость ветра: {self.wind_speed} м/с"
            if self.wind_gusts is not None:
                wind_str += f" ({self.wind_gusts} м/с)"
            lines.append(wind_str)
        if self.wind_direction is not None:
            lines.append(f"🧭 Направление ветра: {format_wind_direction(self.wind_direction)}")
        if self.humidity is not None:
            lines.append(f"💧 Влажность: {self.humidity}%")
        if self.precipitation is not None:
            lines.append(f"🌧 Осадки: {self.precipitation} мм")
        return "\n".join(lines)

    def to_graph_series(self) -> dict[str, list[float]]:
        """Данные для построения графика (по одной точке на параметр)."""
        series = {}
        if self.temperature is not None:
            series["temperature"] = [self.temperature]
        if self.wind_speed is not None:
            series["wind_speed"] = [self.wind_speed]
        if self.wind_gusts is not None:
            series["wind_gusts"] = [self.wind_gusts]
        if self.wind_direction is not None:
            series["wind_direction"] = [self.wind_direction]
        if self.precipitation is not None:
            series["precipitation"] = [self.precipitation]
        if self.humidity is not None:
            series["humidity"] = [self.humidity]
        if self.battery is not None:
            series["battery"] = [self.battery]
        return series


# Символы минуса: ASCII и Unicode (U+2212) — на странице часто используют −
_MINUS_CHARS = "\u2212\u2013\u2014-"  # − – — -

# Направление ветра: градусы → (буквенное обозначение, стрелка)
# С=Сев, В=Вост, Ю=Юг, З=Зап. Стрелка показывает, откуда дует ветер.
_WIND_DIRS = [
    (22.5, 67.5, "С-В", "↗"),
    (67.5, 112.5, "В", "→"),
    (112.5, 157.5, "Ю-В", "↘"),
    (157.5, 202.5, "Ю", "↓"),
    (202.5, 247.5, "Ю-З", "↙"),
    (247.5, 292.5, "З", "←"),
    (292.5, 337.5, "С-З", "↖"),
]


def format_wind_direction(degrees: Optional[float]) -> str:
    """Форматирует направление ветра: градусы + буквенное обозначение + стрелка."""
    if degrees is None:
        return "—"
    d = float(degrees) % 360
    if d >= 337.5 or d < 22.5:
        return f"{int(degrees)}° С ↑"
    for lo, hi, name, arrow in _WIND_DIRS:
        if lo <= d < hi:
            return f"{int(degrees)}° {name} {arrow}"
    return f"{int(degrees)}° С ↑"


def _extract_number(text: str) -> Optional[float]:
    """
    Извлечь первое число из строки (включая отрицательные и дробные).
    Учитывает Unicode минус (−) и запятую как десятичный разделитель.
    """
    if not text:
        return None
    s = str(text).strip()
    for ch in _MINUS_CHARS:
        s = s.replace(ch, "-")
    s = s.replace(",", ".")
    match = re.search(r"-?\d+\.?\d*", s)
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None


# Маппинг русских и английских подписей к полям.
# Не используем слишком короткие ключи ("t" и т.п.): "t" совпадал с "meteo-icon" и давал неверную температуру из "1 ч.".
LABEL_MAP = {
    "температура": "temperature",
    "temp": "temperature",
    "ветер": "wind_speed",
    "wind": "wind_speed",
    "скорость ветра": "wind_speed",
    "порывы": "wind_gusts",
    "gust": "wind_gusts",
    "направление": "wind_direction",
    "direction": "wind_direction",
    "осадки": "precipitation",
    "precip": "precipitation",
    "дождь": "precipitation",
    "влажность": "humidity",
    "humidity": "humidity",
    "батарея": "battery",
    "аккумулятор": "battery",
    "battery": "battery",
    "charge": "battery",
}


def _match_label(text: str) -> Optional[str]:
    """Определить поле по подписи (целое слово/подстрока, без случайных вхождений вроде 't' в 'meteo')."""
    t = text.lower().strip()
    for key, field_name in LABEL_MAP.items():
        if key in t:
            return field_name
    return None


def _log_parsed_data(data: WeatherData, source: str = "scrape") -> None:
    """Вывести в лог все распарсенные поля после скрейпа."""
    logger.info(
        "[%s] Распарсенные данные: temperature=%s, wind_speed=%s, wind_gusts=%s, "
        "wind_direction=%s, precipitation=%s, battery=%s, timestamp=%s, raw_text_len=%s",
        source,
        data.temperature,
        data.wind_speed,
        data.wind_gusts,
        data.wind_direction,
        data.precipitation,
        data.battery,
        data.timestamp,
        len(data.raw_text or ""),
    )


class MonitoringScraper:
    """Скрапер страницы мониторинга метеостанций."""

    def __init__(
        self,
        url: str = MONITOR_URL,
        login: str = MONITOR_LOGIN,
        password: str = MONITOR_PASSWORD,
        timeout: int = 15,
    ):
        self.url = url.rstrip("/")
        self._login = login
        self._password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        })

    def _find_login_form(self, soup: BeautifulSoup) -> Optional[dict]:
        """Найти форму входа и собрать payload для POST."""
        form = soup.find("form")
        if not form:
            return None

        from urllib.parse import urljoin, urlparse
        base = self.url.rsplit("/", 1)[0] + "/"  # директория index.php
        action = form.get("action") or self.url
        action = urljoin(base, action)

        payload: dict[str, str] = {}
        login_field: Optional[str] = None
        password_field: Optional[str] = None

        for inp in form.find_all(["input", "textarea"]):
            name = inp.get("name")
            if not name:
                continue
            if inp.get("type") in ("submit", "button", "image"):
                continue
            if inp.get("type") == "password":
                password_field = name
                payload[name] = self._password
            elif inp.get("type") in ("text", "email") or inp.name == "textarea":
                if any(k in name.lower() for k in ("login", "user", "name", "username", "логин")):
                    login_field = name
                    payload[name] = self._login
                else:
                    payload[name] = inp.get("value", "")
            elif inp.get("type") in ("checkbox", "radio"):
                if name == "remember":
                    payload[name] = inp.get("value", "1")  # Запомнить — отправляем
                elif inp.get("checked"):
                    payload[name] = inp.get("value", "on")
            elif inp.get("type") == "hidden":
                payload[name] = inp.get("value", "")

        if not login_field:
            for inp in form.find_all("input", {"type": "text"}):
                if inp.get("name") and inp.get("name") not in payload:
                    payload[inp["name"]] = self._login
                    break
        if not password_field:
            for inp in form.find_all("input", {"type": "password"}):
                if inp.get("name"):
                    payload[inp["name"]] = self._password
                    break

        return {"action": action, "payload": payload}

    def _parse_table(self, soup: BeautifulSoup, data: WeatherData) -> None:
        """Парсинг таблиц с данными."""
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                label_cell = " ".join(cells[0].get_text(separator=" ", strip=True).split())
                value_cell = cells[1] if len(cells) > 1 else cells[0]
                value_text = value_cell.get_text(separator=" ", strip=True)
                num = _extract_number(value_text)
                field_name = _match_label(label_cell)
                if field_name and num is not None:
                    setattr(data, field_name, num)

    def _parse_divs_spans(self, soup: BeautifulSoup, data: WeatherData) -> None:
        """
        Парсинг div/span по классам. Требуем целое слово в классе (например " temp "),
        чтобы не принять "meteo-icon" за температуру и не взять число из «1 ч.».
        """
        # Явные классы со страницы (значения заполняются JS, в HTML часто "---")
        if data.precipitation is None:
            el = soup.find(class_=re.compile(r"sum-1H-val|sum_1H_val", re.I))
            if el:
                num = _extract_number(el.get_text(strip=True))
                if num is not None:
                    data.precipitation = num
                    logger.info("[requests] precipitation: из .sum-1H-val %r -> %s", el.get_text(strip=True)[:50], num)
        for elem in soup.find_all(True, recursive=True):
            text = elem.get_text(strip=True)
            if not text or len(text) > 100:
                continue
            cls = " " + " ".join(elem.get("class", [])) + " "
            for key, field_name in LABEL_MAP.items():
                key_in_cls = f" {key} " in cls
                key_in_text = key in text.lower()
                if not (key_in_cls or key_in_text):
                    continue
                if " ч." in text or " ч " in text:
                    continue
                num = _extract_number(text)
                if num is not None and getattr(data, field_name) is None:
                    setattr(data, field_name, num)
                    logger.info("[requests] %s: из текста %r -> %s", field_name, text[:80], num)
                    break

    def _parse_text_blocks(self, soup: BeautifulSoup, data: WeatherData) -> None:
        """Парсинг текстовых блоков вида 'Параметр: значение'."""
        for elem in soup.find_all(["p", "div", "span", "li"]):
            text = elem.get_text(separator=" ", strip=True)
            for key, field_name in LABEL_MAP.items():
                if key in text.lower() and ":" in text:
                    parts = re.split(r"[:：]", text, 1)
                    if len(parts) == 2 and key in parts[0].lower():
                        num = _extract_number(parts[1])
                        if num is not None and getattr(data, field_name) is None:
                            setattr(data, field_name, num)
                            break

    def login(self) -> bool:
        """Выполнить вход на страницу."""
        try:
            resp = self.session.get(self.url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Ошибка загрузки страницы: %s", e)
            return False

        soup = BeautifulSoup(resp.text, "html.parser")
        form_data = self._find_login_form(soup)

        if not form_data:
            logger.warning("Форма входа не найдена. Возможно, уже авторизованы.")
            return True

        action = form_data["action"]
        payload = form_data["payload"]
        if not payload:
            logger.warning("Не удалось собрать данные формы.")
            return True

        try:
            from urllib.parse import urlparse
            origin = f"{urlparse(self.url).scheme}://{urlparse(self.url).netloc}"
            headers = {
                "Referer": self.url,
                "Origin": origin,
            }
            post_resp = self.session.post(action, data=payload, headers=headers, timeout=self.timeout)
            post_resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Ошибка авторизации: %s", e)
            return False

        return True

    def _wait_and_get_number(self, page, selector: str, timeout_ms: int = 5000) -> tuple[Optional[float], str]:
        """
        Ждём появления элемента, затем ждём замены "---" на значение (JS заполняет поля асинхронно).
        Возвращает (число или None, сырой текст для лога).
        """
        try:
            el = page.wait_for_selector(selector, timeout=timeout_ms)
            if not el:
                return None, ""
            text = el.inner_text().strip()
            # Даём JS время заполнить значение: при "---" ждём и перечитываем до 5 раз
            for _ in range(5):
                if text and text != "---":
                    break
                page.wait_for_timeout(1500)
                text = el.inner_text().strip()
            num = _extract_number(text) if text and text != "---" else None
            return num, text
        except Exception as e:
            logger.debug("Селектор %s: %s", selector, e)
            return None, ""

    def _extract_from_playwright_page(self, page) -> WeatherData:
        """
        Извлечь данные с JS-рендеренной страницы.
        Структура блока «Температура и влажность» (#data_TH): 1) температура воздуха, 2) влажность, 3) точка росы.
        На скриншоте: −20.5 °C (воздух), 70 %, −24.5 °C (точка росы). Берём только первый span = температура воздуха.
        """
        data = WeatherData(raw_text="")
        # Строгие селекторы по структуре страницы (см. скриншот и debug_after_login.html)
        # Температура: первый дочерний span #data_TH (воздух), влажность — второй, точка росы — третий
        fields = [
            ("temperature", "#data_TH > span:first-child"),
            ("humidity", "#data_TH > span:nth-child(2)"),
            ("wind_speed", "#data_W span.wind-speed"),
            ("wind_gusts", "#data_W span.wind-strong"),
            ("wind_direction", "#actualChart_WD span.wind-direction"),
            ("precipitation", "#data_P_SUM .sum-1H-val"),
            ("battery", "#charge"),
        ]
        for field_name, selector in fields:
            num, raw_text = self._wait_and_get_number(page, selector, timeout_ms=8000)
            if raw_text:
                # repr() покажет Unicode минус (−) как \u2212 — раньше из-за него парсилось +19 вместо −19
                logger.info("[Playwright] %s: сырой текст=%r -> число=%s", field_name, raw_text, num)
            if num is not None:
                setattr(data, field_name, num)
        # Время
        try:
            el = page.query_selector("#actual-date")
            if el:
                data.timestamp = el.inner_text().strip()
        except Exception:
            pass
        # Ожидаемые значения (по скриншоту 12:10 МСК): темп. −20.5 °C, ветер 6.9/4.5 м/с, осадки 0.10/0.20 мм, направление 335°
        _log_parsed_data(data, "Playwright")
        return data

    def fetch_weather_playwright(self) -> WeatherData:
        """Получить данные через Playwright (для JS-страниц)."""
        if not HAS_PLAYWRIGHT:
            logger.warning("Playwright не установлен. Используйте: pip install playwright && playwright install chromium")
            return self.fetch_weather()

        data = WeatherData(raw_text="")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            try:
                page.goto(self.url, wait_until="networkidle", timeout=self.timeout * 1000)
                # Логин
                page.fill('input[name="login"]', self._login)
                page.fill('input[name="password"]', self._password)
                page.check('input[name="remember"]')
                page.click('button[type="submit"], .login-submit')
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(5000)  # Ждём загрузки данных через AJAX
                data = self._extract_from_playwright_page(page)
                data.raw_text = page.content()[:2000]
            except Exception as e:
                logger.exception("Ошибка Playwright: %s", e)
                data.raw_text = str(e)
            finally:
                browser.close()
        return data

    def _weather_data_to_dict(self, data: WeatherData) -> dict:
        """Преобразовать WeatherData в dict для кеширования."""
        return {
            "temperature": data.temperature,
            "wind_speed": data.wind_speed,
            "wind_gusts": data.wind_gusts,
            "wind_direction": data.wind_direction,
            "precipitation": data.precipitation,
            "humidity": data.humidity,
            "battery": data.battery,
            "raw_text": data.raw_text,
            "timestamp": data.timestamp,
        }

    def _dict_to_weather_data(self, d: dict) -> WeatherData:
        """Преобразовать dict из кеша в WeatherData."""
        return WeatherData(
            temperature=d.get("temperature"),
            wind_speed=d.get("wind_speed"),
            wind_gusts=d.get("wind_gusts"),
            wind_direction=d.get("wind_direction"),
            precipitation=d.get("precipitation"),
            humidity=d.get("humidity"),
            battery=d.get("battery"),
            raw_text=d.get("raw_text", ""),
            timestamp=d.get("timestamp"),
        )

    def fetch_weather(self, use_cache: bool = True) -> WeatherData:
        """
        Получить данные о погоде. 
        Сначала проверяет кеш (если use_cache=True), затем обращается к сайту.
        Использует Playwright для JS-страниц при USE_PLAYWRIGHT=true.
        """
        # Проверяем кеш
        if use_cache:
            cached = get_cached_data()
            if cached:
                logger.info("Возвращаем данные из кеша")
                return self._dict_to_weather_data(cached)

        # Кеш устарел или отключён — запрашиваем с сайта
        logger.info("Запрашиваем данные с сайта...")
        if HAS_PLAYWRIGHT and USE_PLAYWRIGHT:
            try:
                data = self.fetch_weather_playwright()
            except Exception as e:
                logger.warning("Playwright не сработал (%s), пробуем requests", e)
                data = self._fetch_weather_requests()
        else:
            data = self._fetch_weather_requests()

        # Сохраняем в кеш
        save_to_cache(self._weather_data_to_dict(data))
        return data

    def _fetch_weather_requests(self) -> WeatherData:
        """Получить данные через requests+BeautifulSoup (без JS)."""
        data = WeatherData(raw_text="")
        if not self.login():
            return data
        try:
            resp = self.session.get(self.url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Ошибка загрузки данных: %s", e)
            data.raw_text = str(e)
            return data
        soup = BeautifulSoup(resp.text, "html.parser")
        data.raw_text = soup.get_text(separator=" ", strip=True)[:2000]
        self._parse_table(soup, data)
        self._parse_divs_spans(soup, data)
        self._parse_text_blocks(soup, data)
        time_match = re.search(r"\d{1,2}[.:]\d{2}(?:[.:]\d{2})?", data.raw_text)
        if time_match:
            data.timestamp = time_match.group()
        _log_parsed_data(data, "requests")
        return data
