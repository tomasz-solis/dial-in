"""Global CSS for the Dial In Streamlit shell."""

from __future__ import annotations


def app_styles() -> str:
    """Return the global CSS for the Dial In Streamlit shell."""

    return """
    <style>
    :root {
        --di-ink: #111111;
        --di-muted: #5f6673;
        --di-line: #dde3e8;
        --di-paper: #ffffff;
        --di-bg: #f5f7f6;
        --di-mint: #83d7c0;
        --di-mint-dark: #1b7f68;
        --di-green: #22a879;
        --di-yellow: #f2c94c;
        --di-red: #d24b3f;
        --di-shadow: 0 18px 42px rgba(17, 17, 17, 0.08);
    }
    .stApp {
        background:
            linear-gradient(180deg, rgba(255,255,255,0.94) 0%, rgba(245,247,246,0.98) 360px),
            radial-gradient(circle at 16% 4%, rgba(131, 215, 192, 0.18), transparent 24%),
            var(--di-bg);
        color: var(--di-ink);
    }
    header[data-testid="stHeader"] {
        background: rgba(255,255,255,0);
    }
    [data-testid="stToolbar"] {
        display: none;
    }
    [data-testid="stSidebar"] {
        background:
            linear-gradient(180deg, rgba(250,252,251,0.98), rgba(239,244,242,0.98));
        border-right: 1px solid #cfd8d4;
        box-shadow: 12px 0 34px rgba(17, 17, 17, 0.045);
    }
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        padding-top: 1.25rem;
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        font-size: 0.9rem;
        line-height: 1.15;
        margin: 1.15rem 0 0.45rem;
        text-transform: uppercase;
        color: var(--di-muted);
    }
    .di-sidebar-user,
    .di-sidebar-panel {
        border: 1px solid #d4ddd9;
        border-radius: 14px;
        background:
            linear-gradient(180deg, rgba(255,255,255,0.98), rgba(247,250,248,0.96));
        padding: 0.9rem;
        box-shadow:
            0 16px 34px rgba(17, 17, 17, 0.075),
            inset 0 1px 0 rgba(255,255,255,0.92);
    }
    .di-sidebar-user {
        margin: 0.7rem 0 1.45rem;
    }
    .di-sidebar-panel {
        margin: 0.35rem 0 1.35rem;
    }
    .di-sidebar-user span,
    .di-sidebar-kicker {
        display: block;
        color: var(--di-muted);
        font-size: 0.7rem;
        font-weight: 850;
        text-transform: uppercase;
    }
    .di-sidebar-user strong,
    .di-sidebar-panel strong {
        display: block;
        margin-top: 0.2rem;
        color: var(--di-ink);
        font-size: 1rem;
        line-height: 1.15;
    }
    .di-sidebar-panel p {
        margin: 0.35rem 0 0;
        color: var(--di-muted);
        font-size: 0.78rem;
        line-height: 1.25;
    }
    .di-sidebar-action-label {
        margin: 1.05rem 0 0.45rem;
        color: var(--di-muted);
        font-size: 0.7rem;
        font-weight: 850;
        letter-spacing: 0;
        text-transform: uppercase;
    }
    .block-container {
        max-width: 1200px;
        padding-top: 1rem;
        padding-bottom: 3rem;
    }
    h1, h2, h3, h4 { letter-spacing: 0; }
    h2, h3 { color: var(--di-ink); }
    .di-topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        padding: 0.2rem 0 1rem;
    }
    .di-brand {
        font-size: clamp(2.25rem, 4.7vw, 5.2rem);
        line-height: 0.9;
        font-weight: 950;
        letter-spacing: 0;
    }
    .di-location {
        margin-top: 0.4rem;
        color: var(--di-muted);
        font-size: 1rem;
        font-weight: 650;
    }
    .di-date-stack {
        min-width: 226px;
        border: 1px solid var(--di-line);
        border-radius: 14px;
        background: rgba(255,255,255,0.82);
        display: grid;
        gap: 0.34rem;
        padding: 0.72rem 0.85rem;
        text-align: left;
        box-shadow: 0 12px 28px rgba(17, 17, 17, 0.055);
        backdrop-filter: blur(14px);
    }
    .di-date-row {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 0.8rem;
    }
    .di-date-row span {
        display: inline;
        color: var(--di-muted);
        font-size: 0.7rem;
        font-weight: 850;
        text-transform: uppercase;
    }
    .di-date-row strong {
        display: inline;
        margin-top: 0;
        color: var(--di-ink);
        font-size: 0.86rem;
        font-weight: 850;
        white-space: nowrap;
    }
    .di-date-row-primary strong {
        font-size: 1.02rem;
        font-weight: 920;
    }
    .di-section-heading { margin: 1.15rem 0 0.7rem; }
    .di-section-kicker {
        color: var(--di-mint-dark);
        font-size: 0.76rem;
        font-weight: 850;
        text-transform: uppercase;
    }
    .di-section-heading h2 {
        margin: 0.1rem 0 0;
        font-size: clamp(1.6rem, 2.6vw, 2.45rem);
        line-height: 1.04;
        font-weight: 900;
    }
    .di-hero {
        overflow: hidden;
        border: 1px solid #151515;
        border-radius: 18px;
        background:
            radial-gradient(circle at 4% 0%, rgba(131, 215, 192, 0.42), transparent 30%),
            linear-gradient(135deg, #111111 0%, #242424 76%, #1c3f37 100%);
        color: #ffffff;
        padding: clamp(1rem, 1.8vw, 1.35rem);
        margin: 0.2rem 0 1rem;
        box-shadow: 0 24px 56px rgba(17, 17, 17, 0.2);
    }
    .di-hero-copy {
        display: flex;
        flex-direction: column;
        justify-content: center;
        padding: clamp(0.6rem, 1.7vw, 1.4rem);
    }
    .di-hero h1 {
        max-width: 760px;
        margin: 0.25rem 0 0.55rem;
        font-size: clamp(2rem, 3.2vw, 3.65rem);
        line-height: 1.02;
        font-weight: 950;
        letter-spacing: 0;
    }
    .di-hero p {
        max-width: 760px;
        color: rgba(255,255,255,0.82);
        font-size: clamp(0.98rem, 1.3vw, 1.12rem);
        margin: 0;
    }
    .di-hero-prep-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.65rem;
        max-width: 760px;
        margin-top: 1rem;
    }
    .di-hero-prep-tile {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        align-items: center;
        gap: 0.85rem;
        border: 1px solid rgba(255,255,255,0.16);
        border-radius: 14px;
        background: rgba(255,255,255,0.1);
        padding: 0.8rem 0.9rem;
    }
    .di-hero-prep-number {
        font-size: clamp(2.35rem, 4vw, 4rem);
        line-height: 0.95;
        font-weight: 950;
        color: #ffffff;
    }
    .di-hero-prep-category {
        color: #ffffff;
        font-size: clamp(1.1rem, 1.6vw, 1.45rem);
        line-height: 1.05;
        font-weight: 900;
    }
    .di-hero-prep-caption {
        margin-top: 0.25rem;
        color: rgba(255,255,255,0.68);
        font-size: 0.8rem;
        line-height: 1.25;
        font-weight: 650;
    }
    .di-eyebrow,
    .di-card-label {
        color: var(--di-muted);
        font-size: 0.74rem;
        font-weight: 850;
        letter-spacing: 0;
        text-transform: uppercase;
    }
    .di-hero .di-eyebrow { color: var(--di-mint); }
    .di-hero-badges,
    .di-chip-row {
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        margin-top: 0.95rem;
    }
    .di-badge,
    .di-chip {
        display: inline-flex;
        align-items: center;
        min-height: 1.65rem;
        border-radius: 999px;
        border: 1px solid rgba(17, 17, 17, 0.1);
        background: #ffffff;
        color: var(--di-ink);
        padding: 0.22rem 0.56rem;
        font-size: 0.72rem;
        font-weight: 800;
        white-space: nowrap;
    }
    .di-badge-dark {
        border-color: rgba(255,255,255,0.18);
        background: rgba(255,255,255,0.14);
        color: #ffffff;
    }
    .di-badge-good { background: rgba(34,168,121,0.12); color: #126044; }
    .di-badge-warn { background: rgba(242,201,76,0.22); color: #755400; }
    .di-badge-risk { background: rgba(210,75,63,0.12); color: #8b281f; }
    .di-hero-reason {
        max-width: 720px;
        margin-top: 0.95rem;
        border-top: 1px solid rgba(255,255,255,0.16);
        padding-top: 0.7rem;
        color: rgba(255,255,255,0.85);
        font-size: clamp(0.95rem, 1.3vw, 1.08rem);
        line-height: 1.4;
    }
    .di-card,
    div[data-testid="stMetric"] {
        background: rgba(255,255,255,0.92);
        border: 1px solid var(--di-line);
        border-radius: 14px;
        padding: 1rem;
        box-shadow: var(--di-shadow);
    }
    .di-card-value {
        color: var(--di-ink);
        font-size: 3.35rem;
        line-height: 1;
        font-weight: 950;
        margin-top: 0.25rem;
    }
    .di-context-value,
    .di-metric-value {
        color: var(--di-ink);
        font-size: 1.25rem;
        line-height: 1.15;
        font-weight: 850;
        margin-top: 0.35rem;
        white-space: normal;
        overflow-wrap: anywhere;
    }
    .di-metric-value {
        font-size: clamp(2rem, 3vw, 3.15rem);
        font-weight: 950;
    }
    .di-card-caption {
        color: var(--di-muted);
        font-size: 0.83rem;
        margin-top: 0.45rem;
    }
    .di-context-card,
    .di-proof-card { margin-bottom: 0.7rem; }
    .di-card-grid {
        display: grid;
        gap: 0.8rem;
        margin: 0.45rem 0 1.05rem;
    }
    .di-card-grid-2 {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .di-card-grid-3 {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .di-card-grid-4 {
        grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    .di-card-grid .di-context-card,
    .di-card-grid .di-proof-card,
    .di-card-grid .di-metric-card {
        min-height: 132px;
        margin-bottom: 0;
    }
    .di-metric-card,
    .di-flow-card {
        min-height: 128px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .di-card-dark {
        background: #111111;
        color: #ffffff;
        border-color: #111111;
    }
    .di-card-dark .di-card-label,
    .di-card-dark .di-card-caption { color: rgba(255,255,255,0.66); }
    .di-card-dark .di-metric-value { color: #ffffff; }
    .di-card-mint { background: #e9f8f3; border-color: #c5eadf; }
    .di-flow-value {
        color: var(--di-ink);
        font-size: clamp(2.1rem, 3vw, 3.35rem);
        line-height: 1.02;
        font-weight: 950;
        margin-top: 0.35rem;
        overflow-wrap: anywhere;
        white-space: normal;
    }
    .di-flow-text {
        font-size: clamp(1.45rem, 2.2vw, 2.5rem);
        line-height: 1.08;
    }
    .di-hours-header {
        min-height: 1.8rem;
        color: var(--di-muted);
        font-size: 0.74rem;
        font-weight: 850;
        text-transform: uppercase;
    }
    .di-hours-day {
        min-height: 2.75rem;
        display: flex;
        align-items: center;
        font-weight: 850;
    }
    .di-empty-state {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        border: 1px dashed #cbd5df;
        border-radius: 14px;
        background: rgba(255,255,255,0.65);
        padding: 1rem;
        color: var(--di-muted);
    }
    .di-empty-state strong { color: var(--di-ink); }
    .di-empty-state-list ul {
        margin: 0.3rem 0 0;
        padding-left: 1.15rem;
    }
    .di-empty-state-list li {
        margin: 0.18rem 0;
        color: var(--di-muted);
    }
    .di-closeout-status {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.7rem;
        margin: 0.55rem 0 1rem;
    }
    .di-closeout-status-item {
        border: 1px solid var(--di-line);
        border-radius: 14px;
        background: rgba(255,255,255,0.88);
        padding: 0.8rem 0.9rem;
        box-shadow: 0 10px 24px rgba(17, 17, 17, 0.045);
    }
    .di-closeout-status-item span {
        display: block;
        color: var(--di-muted);
        font-size: 0.7rem;
        font-weight: 850;
        text-transform: uppercase;
    }
    .di-closeout-status-item strong {
        display: block;
        margin-top: 0.22rem;
        color: var(--di-ink);
        font-size: clamp(0.95rem, 1.2vw, 1.08rem);
        line-height: 1.15;
        white-space: normal;
        overflow-wrap: anywhere;
    }
    .di-form-section {
        border-top: 1px solid var(--di-line);
        margin: 1.15rem 0 0.7rem;
        padding-top: 0.9rem;
    }
    .di-form-section:first-child {
        border-top: 0;
        margin-top: 0;
        padding-top: 0;
    }
    .di-form-section strong {
        display: block;
        color: var(--di-ink);
        font-size: 1rem;
        line-height: 1.15;
    }
    .di-form-section p {
        margin: 0.25rem 0 0;
        color: var(--di-muted);
        font-size: 0.82rem;
        line-height: 1.3;
    }
    div[data-testid="stMetric"] { box-shadow: none; }
    div[data-testid="stMetricLabel"] { color: var(--di-muted); }
    [data-testid="stForm"] {
        border: 1px solid var(--di-line);
        border-radius: 16px;
        background: rgba(255,255,255,0.9);
        padding: 1.1rem;
        box-shadow: var(--di-shadow);
    }
    [data-testid="stTextInput"] label,
    [data-testid="stNumberInput"] label,
    [data-testid="stSelectbox"] label,
    [data-testid="stTimeInput"] label,
    [data-testid="stCheckbox"] label {
        color: var(--di-ink);
        font-weight: 780;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.35rem;
        border-bottom: 1px solid var(--di-line);
        background: rgba(255,255,255,0.58);
        border-radius: 14px 14px 0 0;
        padding: 0.25rem 0.25rem 0;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 12px 12px 0 0;
        padding: 0.72rem 0.95rem;
        color: var(--di-muted);
        font-weight: 760;
    }
    .stTabs [aria-selected="true"] {
        background: #ffffff;
        color: var(--di-ink);
        font-weight: 900;
        box-shadow: 0 -1px 0 #ffffff inset;
    }
    .stButton > button,
    div[data-testid="stFormSubmitButton"] button {
        border-radius: 12px;
        border: 1px solid var(--di-ink);
        background: var(--di-ink);
        color: #ffffff;
        font-weight: 850;
        min-height: 2.85rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    .stButton > button:hover,
    div[data-testid="stFormSubmitButton"] button:hover {
        border-color: var(--di-green);
        background: var(--di-green);
        color: #ffffff;
    }
    [data-testid="stSidebar"] .stButton > button,
    [data-testid="stSidebar"] div[data-testid="stButton"] button,
    section[data-testid="stSidebar"] .stButton > button,
    section[data-testid="stSidebar"] div[data-testid="stButton"] button {
        width: 100%;
        justify-content: flex-start;
        border: 1px solid #c7d3ce !important;
        border-radius: 14px !important;
        background:
            linear-gradient(180deg, #ffffff, #f2f6f4) !important;
        color: var(--di-ink) !important;
        box-shadow:
            0 14px 28px rgba(17, 17, 17, 0.085),
            inset 0 1px 0 rgba(255,255,255,0.92) !important;
        min-height: 2.7rem;
    }
    [data-testid="stSidebar"] .stButton,
    [data-testid="stSidebar"] div[data-testid="stButton"],
    section[data-testid="stSidebar"] .stButton,
    section[data-testid="stSidebar"] div[data-testid="stButton"] {
        margin: 0.7rem 0 !important;
    }
    [data-testid="stSidebar"] .stButton:first-of-type,
    [data-testid="stSidebar"] div[data-testid="stButton"]:first-of-type,
    section[data-testid="stSidebar"] .stButton:first-of-type,
    section[data-testid="stSidebar"] div[data-testid="stButton"]:first-of-type {
        margin-top: 0.95rem !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover,
    [data-testid="stSidebar"] div[data-testid="stButton"] button:hover,
    section[data-testid="stSidebar"] .stButton > button:hover,
    section[data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
        border-color: var(--di-green) !important;
        background: #e9f7f2 !important;
        color: var(--di-ink) !important;
    }
    div[data-testid="stDataFrame"] {
        border-radius: 14px;
        overflow: hidden;
        border: 1px solid var(--di-line);
    }
    @media (max-width: 760px) {
        .block-container { padding-left: 1rem; padding-right: 1rem; }
        .di-topbar {
            align-items: flex-start;
            flex-direction: column;
        }
        .di-date-stack {
            width: 100%;
        }
        .di-card-grid,
        .di-card-grid-2,
        .di-card-grid-3,
        .di-card-grid-4 {
            grid-template-columns: 1fr;
        }
        .di-closeout-status {
            grid-template-columns: 1fr 1fr;
        }
        .di-hero {
            padding: 1rem;
        }
        .di-hero-copy { padding: 0.4rem 0.2rem; }
        .di-hero-prep-grid {
            grid-template-columns: 1fr;
        }
        .di-badge,
        .di-chip { white-space: normal; }
        .stTabs [data-baseweb="tab-list"] {
            overflow-x: auto;
            flex-wrap: nowrap;
        }
        .stTabs [data-baseweb="tab"] {
            white-space: nowrap;
        }
        [data-testid="stForm"] {
            padding: 0.9rem;
        }
    }
    </style>
    """
