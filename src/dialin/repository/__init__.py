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
from dialin.repository.pos import apply_pos_import, fetch_recent_pos_import_runs
from dialin.repository.reads import (
    fetch_data_corrections,
    fetch_history_frames,
    fetch_recommendation_outcomes,
    latest_business_date,
    scorecard,
)
from dialin.repository.recommendations import (
    fetch_latest_recommendations,
    fetch_recommendation_context,
    fetch_recommendations_for_date,
    generate_and_store_recommendations,
    persist_recommendations,
)

__all__ = [
    "OVERRIDE_REASON_OPTIONS",
    "apply_pos_import",
    "build_intraday_pressure_curve",
    "correction_changes",
    "correction_input_source",
    "economics_service_quantile",
    "effective_location_hours",
    "expected_intraday_drinks",
    "fetch_category_economics",
    "fetch_data_corrections",
    "fetch_events_for_window",
    "fetch_history_frames",
    "fetch_intraday_demo",
    "fetch_latest_recommendations",
    "fetch_location_hours_plan",
    "fetch_recent_pos_import_runs",
    "fetch_recommendation_context",
    "fetch_recommendation_outcomes",
    "fetch_recommendations_for_date",
    "generate_and_store_recommendations",
    "insert_manual_event",
    "latest_business_date",
    "list_locations",
    "mark_closed_day",
    "mark_missing_input",
    "normalize_menu_version",
    "normalize_override_reason",
    "persist_recommendations",
    "recommendation_adhered",
    "scorecard",
    "upsert_category_economics",
    "upsert_closeout",
    "upsert_location_hours",
]
