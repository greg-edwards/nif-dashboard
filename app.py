import streamlit as st
import geopandas as gpd
gpd.options.io_engine = "pyogrio"
import pandas as pd
import pydeck as pdk
from pathlib import Path

# ======================================================
# Page configuration
# ======================================================
st.set_page_config(
    page_title="Auckland Network Importance Framework",
    layout="wide"
)


#password

def check_password():
    """Returns True if the user has entered the correct password."""

    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["authenticated"] = True
            del st.session_state["password"]
        else:
            st.session_state["authenticated"] = False

    if "authenticated" not in st.session_state:
        st.text_input(
            "Password",
            type="password",
            on_change=password_entered,
            key="password",
        )
        return False

    if not st.session_state["authenticated"]:
        st.text_input(
            "Password",
            type="password",
            on_change=password_entered,
            key="password",
        )
        st.error("❌ Incorrect password")
        return False

    return True


if not check_password():
    st.stop()



# ======================================================
# File paths
# ======================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "NIF_scoring_v2_updated.geojson"

if not DATA_FILE.exists():
    st.error(f"Required file not found: {DATA_FILE}")
    st.stop()

# ======================================================
# Load data
# ======================================================
@st.cache_data
def load_data():
    gdf = gpd.read_file(DATA_FILE).to_crs(epsg=4326)

    # Make datetime fields JSON‑safe
    for col in gdf.columns:
        if pd.api.types.is_datetime64_any_dtype(gdf[col]):
            gdf[col] = gdf[col].astype(str)

    return gdf

gdf = load_data()

# ======================================================
# User group configuration
# ======================================================
USER_GROUPS = {
    "Combined": {
        "score": "combined_segment_score",
        "level": "combined_segment_criticality",
        "rank": "combined_segment_rank",  # existing
        "derive_rank": False,
    },
    "General Traffic": {
        "score": "general_traffic_score",
        "level": "general_traffic_criticality",
        "rank": "general_traffic_rank",
        "derive_rank": True,
    },
    "Public Transport": {
        "score": "public_transport_score",
        "level": "public_transport_criticality",
        "rank": "public_transport_rank",
        "derive_rank": True,
    },
    "Freight": {
        "score": "freight_score",
        "level": "freight_criticality",
        "rank": "freight_rank",
        "derive_rank": True,
    },
}

LEVELS = ["Level 1", "Level 2", "Level 3", "Level 4", "Level 5"]

# ======================================================
# Sidebar controls
# ======================================================
st.sidebar.title("Road Importance")

user_group = st.sidebar.selectbox(
    "User group",
    options=list(USER_GROUPS.keys())
)

selected_levels = st.sidebar.multiselect(
    "Importance levels",
    options=LEVELS,
    default=LEVELS
)

max_features = st.sidebar.slider(
    "Max corridor segments on map",
    1_000, 50_000, 15_000, 1_000
)

cfg = USER_GROUPS[user_group]

# ======================================================
# Prepared by section (sidebar footer)
# ======================================================
st.sidebar.markdown("---")

BASE_DIR = Path(__file__).resolve().parent
BECA_LOGO = BASE_DIR / "assets" / "beca_logo.png"

if BECA_LOGO.exists():
    st.sidebar.image(
        str(BECA_LOGO),
        width=200
    )

st.sidebar.markdown(
    """
    **Prepared by**  
    Beca Limited  

    *Auckland Transport Network Resilience Study*

    For questions on this tool, email greg.edwards@beca.com
    """,
    unsafe_allow_html=False
)

# ======================================================
# Normalise level text
# ======================================================
for c in USER_GROUPS.values():
    gdf[c["level"]] = gdf[c["level"]].astype(str).str.strip()

# ======================================================
# Prepare TABLE dataframe
# ======================================================
df_table = gdf[gdf[cfg["level"]].isin(selected_levels)].copy()

# Derive rank if required
if cfg["derive_rank"]:
    df_table[cfg["rank"]] = (
        df_table[cfg["score"]]
        .rank(method="dense", ascending=False)
        .astype(int)
    )

if df_table.empty:
    st.warning("No corridors match the selected filters.")
    st.stop()

# ======================================================
# Prepare MAP dataframe
# ======================================================
df_map = df_table.copy()

def geometry_to_path(geom):
    if geom is None or geom.is_empty:
        return None
    return [[float(x), float(y)] for x, y in geom.coords]

df_map["paths"] = df_map.geometry.apply(geometry_to_path)

df_map = df_map[
    df_map["paths"].apply(
        lambda p: isinstance(p, list) and len(p) > 1
    )
]

# Limit map load
df_map = df_map.sort_values(cfg["rank"]).head(max_features)

# ======================================================
# Colour mapping
# ======================================================
LEVEL_COLORS = {
    "Level 1": [128, 0, 38],
    "Level 2": [189, 0, 38],
    "Level 3": [227, 26, 28],
    "Level 4": [252, 78, 42],
    "Level 5": [253, 141, 60],
}

df_map["color"] = df_map[cfg["level"]].map(LEVEL_COLORS)
df_map = df_map[df_map["color"].notna()]

df_map = df_map[
    ["road_name", cfg["rank"], cfg["score"], cfg["level"], "paths", "color"]
].copy()

# ======================================================
# Map
# ======================================================
center_lat = gdf.geometry.centroid.y.mean()
center_lon = gdf.geometry.centroid.x.mean()

layer = pdk.Layer(
    "PathLayer",
    data=df_map,
    get_path="paths",
    get_color="color",
    get_width=6,
    width_min_pixels=3,
    pickable=True,
)

deck = pdk.Deck(
    layers=[layer],
    initial_view_state=pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=9,
    ),
    map_style="light",
    tooltip={
        "html": (
            "<b>{road_name}</b><br/>"
            f"Rank: {{{cfg['rank']}}}<br/>"
            f"Score: {{{cfg['score']}}}"
        )
    },
)

st.subheader("Road Importance Map")
st.pydeck_chart(deck, use_container_width=True)

# ======================================================
# Ranking table
# ======================================================

st.subheader(f"Top corridors (Ranks 1–10) – {user_group}")

rank_table = (
    df_table
    .sort_values(cfg["rank"])
    .loc[:, ["road_name", cfg["rank"], cfg["level"], cfg["score"]]]
    .drop_duplicates("road_name")
)

# ✅ Keep ALL corridors with rank ≤ 10
rank_table = rank_table[rank_table[cfg["rank"]] <= 10]

st.dataframe(rank_table, use_container_width=True)