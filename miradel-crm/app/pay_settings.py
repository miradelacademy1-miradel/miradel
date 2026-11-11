"""TZ-7: `pay.*` settings helper."""
from sqlalchemy.orm import Session

from .models import Setting

DEFAULTS = {
    "default_fee_day": "10",
    "grace_days": "0",
    "billing_start_month": "",
    "first_month_mode": "full",
    "prorate_round": "1000",
    "remind_days_before": "3,1,0",
    "converge_enabled": "false",
    "converge_target_day": "10",
    "converge_months": "3",
}


def pay_setting(db: Session, key: str, default: str = "") -> str:
    s = db.get(Setting, "pay." + key)
    return s.value if s else (default or DEFAULTS.get(key, ""))


def set_pay_setting(db: Session, key: str, value: str) -> None:
    s = db.get(Setting, "pay." + key)
    if not s:
        s = Setting(key="pay." + key)
        db.add(s)
    s.value = value


def load_pay_settings(db: Session) -> dict:
    return {
        "default_fee_day": int(pay_setting(db, "default_fee_day")),
        "grace_days": int(pay_setting(db, "grace_days")),
        "billing_start_month": pay_setting(db, "billing_start_month"),
        "first_month_mode": pay_setting(db, "first_month_mode"),
        "prorate_round": int(pay_setting(db, "prorate_round")),
        "remind_days_before": pay_setting(db, "remind_days_before"),
        "converge_enabled": pay_setting(db, "converge_enabled") == "true",
        "converge_target_day": int(pay_setting(db, "converge_target_day")),
        "converge_months": int(pay_setting(db, "converge_months")),
    }
