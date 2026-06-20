"""Account-scoped data access for the Dial In app and scripts.

Split out of a single module; the public API is re-exported here so
``from dialin.repository import X`` keeps working unchanged.
"""

from dialin.repository.corrections import (
    OVERRIDE_REASON_OPTIONS,
    correction_changes,
    correction_input_source,
    mark_closed_day,
    mark_missing_input,
    normalize_menu_version,
    normalize_override_reason,
    recommendation_adhered,
    upsert_closeout,
)
from dialin.repository.economics import (
    economics_service_quantile,
    fetch_category_economics,
    upsert_category_economics,
)
from dialin.repository.events import fetch_events_for_window, insert_manual_event
from dialin.repository.intraday import (
    build_intraday_pressure_curve,
    expected_intraday_drinks,
    fetch_intraday_demo,
)
from dialin.repository.locations import (
    effective_location_hours,
    fetch_location_hours_plan,
    list_locations,
    upsert_location_hours,
)
from dialin.repository.pilot import (
    PILOT_CHECKLIST_FIELDS,
    PILOT_PHASES,
    fetch_pilot_profile,
    fetch_pilot_windows,
    phase_for_date,
    upsert_pilot_profile,
    upsert_pilot_window,
)
from dialin.repository.pos import apply_pos_import, fetch_recent_pos_import_runs
from dialin.repository.reads import (
    fetch_data_corrections,
    fetch_history_frames,
    fetch_recommendation_outcomes,
    latest_business_date,
    scorecard,
)
from dialin.repository.recommendations import (
    fetch_active_recommendations_for_date,
    fetch_latest_recommendations,
    fetch_recommendation_build_payload,
    fetch_recommendation_context,
    fetch_recommendations_for_date,
    generate_and_store_recommendations,
    insert_recommendation_set,
    persist_recommendations,
    supersede_active_recommendations,
)

__all__ = [
    "OVERRIDE_REASON_OPTIONS",
    "PILOT_CHECKLIST_FIELDS",
    "PILOT_PHASES",
    "apply_pos_import",
    "build_intraday_pressure_curve",
    "correction_changes",
    "correction_input_source",
    "economics_service_quantile",
    "effective_location_hours",
    "expected_intraday_drinks",
    "fetch_active_recommendations_for_date",
    "fetch_category_economics",
    "fetch_data_corrections",
    "fetch_events_for_window",
    "fetch_history_frames",
    "fetch_intraday_demo",
    "fetch_latest_recommendations",
    "fetch_location_hours_plan",
    "fetch_pilot_profile",
    "fetch_pilot_windows",
    "fetch_recent_pos_import_runs",
    "fetch_recommendation_build_payload",
    "fetch_recommendation_context",
    "fetch_recommendation_outcomes",
    "fetch_recommendations_for_date",
    "generate_and_store_recommendations",
    "insert_manual_event",
    "insert_recommendation_set",
    "latest_business_date",
    "list_locations",
    "mark_closed_day",
    "mark_missing_input",
    "normalize_menu_version",
    "normalize_override_reason",
    "persist_recommendations",
    "phase_for_date",
    "recommendation_adhered",
    "scorecard",
    "supersede_active_recommendations",
    "upsert_category_economics",
    "upsert_closeout",
    "upsert_location_hours",
    "upsert_pilot_profile",
    "upsert_pilot_window",
]
