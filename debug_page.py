#!/usr/bin/env python3
"""
Отладка страницы мониторинга: сохранение HTML и анализ формы входа.
"""
import sys
import requests
from bs4 import BeautifulSoup

from config import MONITOR_URL, MONITOR_LOGIN, MONITOR_PASSWORD

def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    })

    print(f"Загрузка {MONITOR_URL}...")
    resp = session.get(MONITOR_URL, timeout=15)
    resp.raise_for_status()

    # Сохраняем HTML для анализа
    with open("debug_page.html", "w", encoding="utf-8") as f:
        f.write(resp.text)
    print("HTML сохранён в debug_page.html")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Анализ форм
    forms = soup.find_all("form")
    print(f"\nНайдено форм: {len(forms)}")
    for i, form in enumerate(forms):
        print(f"\n--- Форма {i+1} ---")
        print("  action:", form.get("action"))
        print("  method:", form.get("method", "GET"))
        for inp in form.find_all(["input", "textarea"]):
            print(f"  input: name={inp.get('name')} type={inp.get('type')} value={inp.get('value', '')[:30]}")

    # Попытка авторизации
    if forms:
        form = forms[0]
        from urllib.parse import urljoin
        action = urljoin(MONITOR_URL, form.get("action", ""))
        payload = {}
        for inp in form.find_all(["input", "textarea"]):
            name = inp.get("name")
            if not name or inp.get("type") in ("submit", "button", "image"):
                continue
            if inp.get("type") == "password":
                payload[name] = MONITOR_PASSWORD
            elif inp.get("type") in ("text", "email"):
                payload[name] = MONITOR_LOGIN
            elif inp.get("type") == "hidden":
                payload[name] = inp.get("value", "")
            elif inp.get("type") in ("checkbox", "radio"):
                payload[name] = inp.get("value", "1") if name == "remember" else (inp.get("value", "on") if inp.get("checked") else None)
        payload = {k: v for k, v in payload.items() if v is not None}
        print(f"\n--- POST на {action} ---")
        print("  payload:", payload)

        post_resp = session.post(action, data=payload, timeout=15)
        with open("debug_after_login.html", "w", encoding="utf-8") as f:
            f.write(post_resp.text)
        print("  Ответ сохранён в debug_after_login.html")
        print("  Статус:", post_resp.status_code)
        print("  Длина:", len(post_resp.text))
        # Проверяем, остались ли на странице входа
        if "Войти" in post_resp.text and "Запомнить" in post_resp.text:
            print("  ⚠️ Похоже, всё ещё на странице входа - логин мог не сработать")
        else:
            print("  ✓ Похоже, авторизация прошла успешно")


if __name__ == "__main__":
    main()
