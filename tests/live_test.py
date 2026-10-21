"""Проверка blueprint на живом HA без реальных устройств: временные помощники вместо датчиков и лампы,
временное расписание, временная автоматизация по blueprint. Всё созданное удаляется в конце.
Запуск: python tests/live_test.py   (доступ к HA - через ../ha-voice/ha_api.py)"""
import base64
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent / "ha-voice"))
import ha_api as h  # noqa: E402
from ha_api import deploy  # noqa: E402

BP_DIR = "/config/blueprints/automation/zz_test"
BP_PATH = "zz_test/motion.yaml"
AUTO_ID = "zz_test_motion_blueprint"
DELAY = 3
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def state(e):
    return h.api(f"/api/states/{e}")["state"]


def set_bool(e, on):
    h.api(f"/api/services/input_boolean/turn_{'on' if on else 'off'}", {"entity_id": e})


def upload_blueprint():
    lines = base64.encodebytes((ROOT / "advanced_motion_light_blueprint.yaml").read_bytes()).decode().splitlines()
    tt = deploy.terminal(h.WS)
    deploy.send(tt, "\x03", 0.3)
    deploy.send(tt, f"stty -echo; mkdir -p {BP_DIR}; cat > /tmp/bp.b64\r", 1)
    for i in range(0, len(lines), 50):
        deploy.send(tt, "\r".join(lines[i:i + 50]) + "\r", 0.05)
    deploy.send(tt, "\x04", 1)
    deploy.send(tt, f"stty echo; base64 -d /tmp/bp.b64 > {BP_DIR}/motion.yaml; rm /tmp/bp.b64\r", 2)
    h.WS.call(type="blueprint/list", domain="automation")


def schedule_days(active):
    """Период на сегодня: вокруг текущего времени (active) или далеко от него."""
    now = datetime.now()
    if active:
        a, b = max(now - timedelta(hours=1), now.replace(hour=0, minute=0, second=0)), now + timedelta(hours=1)
        b = min(b, now.replace(hour=23, minute=59, second=0))
    else:
        a = (now + timedelta(hours=3)) if now.hour < 18 else now.replace(hour=0, minute=0, second=0)
        b = a + timedelta(hours=1)
    day = WEEKDAYS[now.weekday()]
    return {d: ([{"from": a.strftime("%H:%M:%S"), "to": b.strftime("%H:%M:%S")}] if d == day else []) for d in WEEKDAYS}


def main():
    created = {}
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= cond
        print("OK  " if cond else "FAIL", name)

    try:
        for key in ("s1", "s2", "lamp"):
            r = h.WS.call(type="input_boolean/create", name=f"zz test {key}")
            created[key] = r["id"]
        s1, s2, lamp = (f"input_boolean.{created[k]}" for k in ("s1", "s2", "lamp"))
        r = h.WS.call(type="schedule/create", name="zz test schedule", **schedule_days(True))
        created["schedule"] = r["id"]
        sched = f"schedule.{r['id']}"
        upload_blueprint()
        h.api(f"/api/config/automation/config/{AUTO_ID}", {
            "alias": "zz test motion blueprint", "description": "",
            "use_blueprint": {"path": BP_PATH, "input": {
                "motion_sensors": [s1, s2], "targets": {"entity_id": lamp}, "schedule": sched, "off_delay": DELAY}}})
        time.sleep(3)
        auto = next(s["entity_id"] for s in h.api("/api/states")
                    if s["entity_id"].startswith("automation.") and s["attributes"].get("id") == AUTO_ID)
        check(f"автоматизация создана и включена ({auto})", state(auto) == "on")
        check(f"расписание активно ({sched})", state(sched) == "on")

        set_bool(s1, True); time.sleep(1.5)
        check("движение на датчике 1 в периоде -> лампа включилась", state(lamp) == "on")
        set_bool(s2, True); set_bool(s1, False); time.sleep(DELAY + 2)
        check("датчик 1 погас, датчик 2 видит -> лампа горит", state(lamp) == "on")
        set_bool(s2, False); time.sleep(DELAY - 1.5)
        check("все погасли, задержка не истекла -> лампа горит", state(lamp) == "on")
        time.sleep(3)
        check("все погасли, задержка истекла -> лампа выключилась", state(lamp) == "off")

        set_bool(s1, True); time.sleep(1); set_bool(s1, False); time.sleep(1.5)
        set_bool(s1, True); time.sleep(DELAY + 1)
        check("движение снова началось во время задержки -> лампа горит", state(lamp) == "on")
        set_bool(s1, False); time.sleep(DELAY + 2)
        check("и выключилась после ухода", state(lamp) == "off")

        h.WS.call(type="schedule/update", schedule_id=created["schedule"], name="zz test schedule", **schedule_days(False))
        time.sleep(2)
        check("расписание неактивно", state(sched) == "off")
        set_bool(s1, True); time.sleep(1.5)
        check("движение вне периода -> лампа не включилась", state(lamp) == "off")
        set_bool(lamp, True); time.sleep(0.5)               # кто-то включил вручную
        set_bool(s1, False); time.sleep(DELAY + 2)
        check("вне периода: нет движения -> лампа выключилась", state(lamp) == "off")
    finally:
        h.api(f"/api/config/automation/config/{AUTO_ID}", method="DELETE")
        for key, i in created.items():
            h.WS.call(type=f"{'schedule' if key == 'schedule' else 'input_boolean'}/delete",
                      **{f"{'schedule' if key == 'schedule' else 'input_boolean'}_id": i})
        deploy.send(deploy.terminal(h.WS), f"rm -rf {BP_DIR}\r", 1)
        h.WS.call(type="blueprint/list", domain="automation")
        print("временные помощники, расписание, автоматизация и blueprint удалены")
    print("\nВСЁ ВЕРНО" if ok else "\nЕСТЬ ОШИБКИ")


if __name__ == "__main__":
    main()
