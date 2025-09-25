
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from io import BytesIO
from scipy.stats import pearsonr, spearmanr

st.set_page_config(page_title="FHEMIG | Custos x Produção", layout="wide")

# ---------------------------
# Helpers
# ---------------------------

PT_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}

MONTH_ORDER = list(range(1,13))
MONTH_LABELS = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]

def normalize_month(m):
    if pd.isna(m):
        return np.nan
    s = str(m).strip().lower()
    # try numeric
    try:
        v = int(float(s))
        if 1 <= v <= 12:
            return v
    except:
        pass
    # try Portuguese name
    return PT_MONTHS.get(s, np.nan)

def make_year_int(y):
    try:
        return int(y)
    except:
        try:
            return int(float(y))
        except:
            return np.nan

def build_year_month(df, ycol, mcol):
    y = df[ycol].apply(make_year_int)
    m = df[mcol].apply(normalize_month)
    dt = pd.to_datetime(dict(year=y, month=m, day=1), errors="coerce")
    return y, m, dt

def pct_change_grouped(df, group_cols, value_col):
    return df.sort_values(["Data","Hospital"]).groupby(group_cols)[value_col].pct_change()

def safediv(a, b):
    with np.errstate(divide='ignore', invalid='ignore'):
        out = np.true_divide(a, b)
        out[~np.isfinite(out)] = np.nan
    return out

def corr_with_pvalue(x, y, method="pearson"):
    x = pd.Series(x).astype(float)
    y = pd.Series(y).astype(float)
    mask = x.notna() & y.notna()
    if mask.sum() < 3:
        return np.nan, np.nan
    if method == "spearman":
        r, p = spearmanr(x[mask], y[mask])
    else:
        r, p = pearsonr(x[mask], y[mask])
    return r, p

def download_link(df, filename):
    buffer = BytesIO()
    df.to_csv(buffer, index=False).seek(0)
    st.download_button("Baixar dados (CSV)", data=buffer, file_name=filename, mime="text/csv")

# ---------------------------
# Sidebar: Data Input
# ---------------------------

st.sidebar.header("📦 Dados de entrada")

# Caminhos fixos no diretório do projeto
default_costs_path = "dados_custos.xlsx"
default_prod_path  = "dados_producao.xlsx"

# Abre diretamente os arquivos do diretório
try:
    costs_xls = pd.ExcelFile(default_costs_path)
    prod_xls  = pd.ExcelFile(default_prod_path)
except Exception as e:
    st.sidebar.error(
        "Erro ao abrir arquivos no diretório. "
        "Verifique se 'dados_custos.xlsx' e 'dados_producao.xlsx' estão na mesma pasta do app."
    )
    st.stop()

# Seleção de abas (mantida)
costs_sheet = st.sidebar.selectbox("Aba de custos", costs_xls.sheet_names, index=0)
prod_sheet  = st.sidebar.selectbox("Aba de produção", prod_xls.sheet_names, index=0)

# Carrega os dados
df_costs_raw = costs_xls.parse(costs_sheet)
df_prod_raw  = prod_xls.parse(prod_sheet)


# Column aliases to improve robustness
COSTS_COLS = {
    "Hospital": ["Hospital","Estabelecimento","Unidade","Unidade/Hospital"],
    "Ano": ["Competência - Ano","Ano","data - Ano","Ano Competência"],
    "Mes": ["Competência - Mês","Mês","data - Mês","Mes Competência"],
    "Grupo": ["Grupo do item","Grupo do Item","Grupo","Grupo de Despesa"],
    "Item": ["Item de Custo","Item","Item de custo"],
    "Valor": ["Valor","Valor (R$)","Valor Total"]
}

PROD_COLS = {
    "Hospital": ["Estabelecimento","Hospital","Unidade","Unidade/Hospital"],
    "Ano": ["data - Ano","Ano","Competência - Ano"],
    "Mes": ["data - Mês","Mês","Competência - Mês"],
    # production metrics will be inferred dynamically (numerical columns)
}

def find_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

# Resolve required columns
c_hosp = find_col(df_costs_raw, COSTS_COLS["Hospital"])
c_ano  = find_col(df_costs_raw, COSTS_COLS["Ano"])
c_mes  = find_col(df_costs_raw, COSTS_COLS["Mes"])
c_grp  = find_col(df_costs_raw, COSTS_COLS["Grupo"])
c_item = find_col(df_costs_raw, COSTS_COLS["Item"])
c_val  = find_col(df_costs_raw, COSTS_COLS["Valor"])

p_hosp = find_col(df_prod_raw,  PROD_COLS["Hospital"])
p_ano  = find_col(df_prod_raw,  PROD_COLS["Ano"])
p_mes  = find_col(df_prod_raw,  PROD_COLS["Mes"])

missing = [name for name, val in {
    "Custos: Hospital": c_hosp, "Custos: Ano": c_ano, "Custos: Mês": c_mes, "Custos: Grupo": c_grp,
    "Custos: Item": c_item, "Custos: Valor": c_val, "Prod: Hospital": p_hosp, "Prod: Ano": p_ano, "Prod: Mês": p_mes
}.items() if val is None]

if missing:
    st.error("Colunas obrigatórias não encontradas: " + ", ".join(missing))
    st.stop()

# ---------------------------
# Prepare data
# ---------------------------

df_costs = df_costs_raw[[c_hosp, c_ano, c_mes, c_grp, c_item, c_val]].copy()
df_costs.columns = ["Hospital","Ano","Mes","Grupo","Item","Valor"]
df_costs["Ano"], df_costs["Mes"], df_costs["Data"] = build_year_month(df_costs, "Ano","Mes")

# Keep only valid rows
df_costs = df_costs.dropna(subset=["Hospital","Ano","Mes","Valor","Data"])

# Aggregate (sum values for duplicates)
df_costs["Valor"] = pd.to_numeric(df_costs["Valor"], errors="coerce")
df_costs = df_costs.groupby(["Hospital","Ano","Mes","Data","Grupo","Item"], as_index=False)["Valor"].sum()

df_prod = df_prod_raw.copy()
# renomeia só as chaves
df_prod = df_prod.rename(columns={p_hosp: "Hospital", p_ano: "Ano", p_mes: "Mes"})
# reordena deixando as chaves na frente
other_cols = [c for c in df_prod.columns if c not in ["Hospital","Ano","Mes"]]
df_prod = df_prod[["Hospital","Ano","Mes"] + other_cols]


# Build date and numeric-only metrics
df_prod["Ano"], df_prod["Mes"], df_prod["Data"] = build_year_month(df_prod, "Ano","Mes")
num_cols = df_prod.select_dtypes(include=[np.number]).columns.tolist()
metric_candidates = [c for c in num_cols if c not in ["Ano","Mes"]]

df_prod = df_prod.dropna(subset=["Hospital","Ano","Mes","Data"])

# ---------------------------
# Sidebar: Filters
# ---------------------------

st.sidebar.header("🔎 Filtros")

# Hospital mapping (opcional): alinhar nomes entre as planilhas
hosp_costs = sorted(df_costs["Hospital"].dropna().unique().tolist())
hosp_prod  = sorted(df_prod["Hospital"].dropna().unique().tolist())

with st.sidebar.expander("Mapeamento de hospitais (opcional)"):
    st.markdown("Se os nomes diferirem entre planilhas, ajuste o mapeamento para unificar.")
    mapping = {}
    for h in hosp_prod:
        mapping[h] = st.selectbox(
            f"Produção '{h}' corresponde a:",
            options=["(mesmo)"] + hosp_costs,
            index=0,
            key=f"map_{h}"
        )

    # Salva a coluna original e aplica o mapeamento de forma segura (sem cruzar DataFrames)
    hosp_orig = df_prod["Hospital"].copy()
    hosp_mapped = hosp_orig.map(lambda x: mapping.get(x, "(mesmo)"))
    # Se ficou "(mesmo)", mantém o original; caso contrário, usa o valor mapeado
    df_prod["Hospital"] = np.where(hosp_mapped.eq("(mesmo)"), hosp_orig, hosp_mapped)


# After mapping, recompute lists
hosp_all = sorted(set(df_costs["Hospital"].unique().tolist()) | set(df_prod["Hospital"].unique().tolist()))
sel_hosp = st.sidebar.multiselect("Hospitais", hosp_all, default=hosp_all)

# Date range
min_date = max(df_costs["Data"].min(), df_prod["Data"].min())
max_date = min(df_costs["Data"].max(), df_prod["Data"].max())
date_range = st.sidebar.slider("Período", min_value=min_date.to_pydatetime(), max_value=max_date.to_pydatetime(),
                               value=(min_date.to_pydatetime(), max_date.to_pydatetime()), format="MM/YYYY")

# Cost selection
groups = ["(Todos)"] + sorted(df_costs["Grupo"].dropna().unique().tolist())
group_sel = st.sidebar.selectbox("Grupo de despesa", groups, index=0)

# Item selection (depends on group)
if group_sel != "(Todos)":
    items = ["(Todos)"] + sorted(df_costs.loc[df_costs["Grupo"]==group_sel, "Item"].dropna().unique().tolist())
else:
    items = ["(Todos)"] + sorted(df_costs["Item"].dropna().unique().tolist())
item_sel = st.sidebar.selectbox("Item de custo", items, index=0)

# Production metric
if not metric_candidates:
    st.error("Não foram encontradas colunas numéricas de produção.")
    st.stop()
metric_sel = st.sidebar.selectbox("Métrica de produção", metric_candidates, index=metric_candidates.index(metric_candidates[0]))

# ---------------------------
# Filtering
# ---------------------------

mask_costs = (
    df_costs["Hospital"].isin(sel_hosp) &
    (df_costs["Data"] >= pd.to_datetime(date_range[0])) &
    (df_costs["Data"] <= pd.to_datetime(date_range[1]))
)
if group_sel != "(Todos)":
    mask_costs &= (df_costs["Grupo"] == group_sel)
if item_sel != "(Todos)":
    mask_costs &= (df_costs["Item"] == item_sel)

dfc = df_costs.loc[mask_costs].copy()

mask_prod = (
    df_prod["Hospital"].isin(sel_hosp) &
    (df_prod["Data"] >= pd.to_datetime(date_range[0])) &
    (df_prod["Data"] <= pd.to_datetime(date_range[1]))
)

dfp = df_prod.loc[mask_prod, ["Hospital","Ano","Mes","Data", metric_sel]].copy()
dfp.rename(columns={metric_sel: "Producao"}, inplace=True)

# Aggregate
dfc_agg = dfc.groupby(["Hospital","Ano","Mes","Data"], as_index=False)["Valor"].sum()
dfp_agg = dfp.groupby(["Hospital","Ano","Mes","Data"], as_index=False)["Producao"].sum()

# Merge
dfm = pd.merge(dfc_agg, dfp_agg, on=["Hospital","Ano","Mes","Data"], how="inner")

# Compute per-hospital KPI and variations
dfm = dfm.sort_values(["Hospital","Data"]).reset_index(drop=True)
dfm["Custo_por_PacienteDia"] = safediv(dfm["Valor"], dfm["Producao"])

dfm["Var_Custo_%"] = dfm.groupby("Hospital")["Valor"].pct_change() * 100.0
dfm["Var_Prod_%"]  = dfm.groupby("Hospital")["Producao"].pct_change() * 100.0
dfm["Var_Custo_por_PacienteDia_%"] = dfm.groupby("Hospital")["Custo_por_PacienteDia"].pct_change() * 100.0

# ---------------------------
# Header
# ---------------------------

st.title("🏥 FHEMIG — Custos × Produção")
st.caption("Ferramenta gerencial para análise da correlação entre variação de custos e produção hospitalar.")

# Summary
left, right = st.columns([2,1])
with left:
    st.subheader("Filtro atual")
    st.markdown(f"- **Hospitais:** {', '.join(sel_hosp)}")
    st.markdown(f"- **Período:** {date_range[0].strftime('%m/%Y')} a {date_range[1].strftime('%m/%Y')}")
    st.markdown(f"- **Grupo:** {group_sel} — **Item:** {item_sel}")
    st.markdown(f"- **Métrica de produção:** `{metric_sel}`")
with right:
    st.metric("Registros após merge", value=len(dfm))

# ---------------------------
# KPIs
# ---------------------------

kpi1, kpi2, kpi3 = st.columns(3)
if not dfm.empty:
    kpi1.metric("Custo total (R$)", f"{dfm['Valor'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
    kpi2.metric(f"Total {metric_sel}", f"{dfm['Producao'].sum():,.0f}".replace(",", "X").replace(".", ",").replace("X","."))
    med = dfm["Custo_por_PacienteDia"].median()
    kpi3.metric("Mediana Custo / Produção", f"{med:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
else:
    st.info("Sem dados no filtro atual. Ajuste os filtros.")

# ---------------------------
# Charts
# ---------------------------

if not dfm.empty:
    st.subheader("Séries temporais")
    chart_base = alt.Chart(dfm).encode(
        x=alt.X("yearmonth(Data):T", title="Competência")
    )
    line_cost = chart_base.mark_line().encode(
        y=alt.Y("Valor:Q", title="Custo (R$)"),
        color=alt.Color("Hospital:N", legend=alt.Legend(title="Hospital"))
    )
    line_prod = chart_base.mark_line().encode(
        y=alt.Y("Producao:Q", title=f"Produção ({metric_sel})"),
        color=alt.Color("Hospital:N", legend=None)
    )
    st.altair_chart(line_cost.properties(height=300).interactive(), use_container_width=True)
    st.altair_chart(line_prod.properties(height=300).interactive(), use_container_width=True)

    st.subheader("Variações % mês a mês")
    var_cols = ["Var_Custo_%", "Var_Prod_%", "Var_Custo_por_PacienteDia_%"]
    var_long = dfm.melt(id_vars=["Hospital","Data"], value_vars=var_cols, var_name="Indicador", value_name="Variacao")
    var_long["Indicador"] = var_long["Indicador"].map({
        "Var_Custo_%":"Custo (%)",
        "Var_Prod_%":"Produção (%)",
        "Var_Custo_por_PacienteDia_%":"Custo/Produção (%)"
    }).fillna(var_long["Indicador"])
    line_var = alt.Chart(var_long).mark_line().encode(
        x=alt.X("yearmonth(Data):T", title="Competência"),
        y=alt.Y("Variacao:Q", title="Variação %"),
        color=alt.Color("Indicador:N"),
        facet=alt.Facet("Hospital:N", columns=1, title=None)
    ).properties(height=180)
    st.altair_chart(line_var, use_container_width=True)

    # ---------------------------
    # Correlation Section
    # ---------------------------
    st.subheader("Correlação")

    method = st.radio("Método", ["pearson","spearman"], horizontal=True, index=0)
    # Correlation between variations (Custo vs Produção)
    r_var, p_var = corr_with_pvalue(dfm["Var_Custo_%"], dfm["Var_Prod_%"], method=method)
    # Level correlation (Custo vs Produção)
    r_lvl, p_lvl = corr_with_pvalue(dfm["Valor"], dfm["Producao"], method=method)

    c1, c2 = st.columns(2)
    c1.metric("Correlação (variações % custo vs % produção)", f"{r_var:.3f}" if pd.notna(r_var) else "N/A", help=f"p-valor: {p_var:.4f}" if pd.notna(p_var) else "")
    c2.metric("Correlação (níveis de custo vs produção)", f"{r_lvl:.3f}" if pd.notna(r_lvl) else "N/A", help=f"p-valor: {p_lvl:.4f}" if pd.notna(p_lvl) else "")

    st.markdown("**Dispersão das variações (%):**")
    scatter_var = alt.Chart(dfm.dropna(subset=["Var_Custo_%","Var_Prod_%"])).mark_circle(size=80, opacity=0.6).encode(
        x=alt.X("Var_Custo_%:Q", title="Variação % do Custo"),
        y=alt.Y("Var_Prod_%:Q", title="Variação % da Produção"),
        color=alt.Color("Hospital:N"),
        tooltip=["Hospital","Data","Var_Custo_%","Var_Prod_%"]
    ).properties(height=350)
    st.altair_chart(scatter_var + scatter_var.transform_regression("Var_Custo_%","Var_Prod_%").mark_line(), use_container_width=True)

    st.markdown("**Dispersão dos níveis (Custo vs Produção):**")
    scatter_lvl = alt.Chart(dfm).mark_circle(size=80, opacity=0.6).encode(
        x=alt.X("Valor:Q", title="Custo (R$)"),
        y=alt.Y("Producao:Q", title=f"Produção ({metric_sel})"),
        color=alt.Color("Hospital:N"),
        tooltip=["Hospital","Data","Valor","Producao"]
    ).properties(height=350)
    st.altair_chart(scatter_lvl + scatter_lvl.transform_regression("Valor","Producao").mark_line(), use_container_width=True)

    # ---------------------------
    # Table and download
    # ---------------------------
    st.subheader("Dados consolidados")
    df_show = dfm.copy()
    df_show["Mes"] = df_show["Data"].dt.month.map(lambda i: MONTH_LABELS[i-1] if pd.notna(i) else "")
    df_show["Ano"] = df_show["Data"].dt.year
    df_show = df_show[["Hospital","Ano","Mes","Data","Valor","Producao","Custo_por_PacienteDia","Var_Custo_%","Var_Prod_%","Var_Custo_por_PacienteDia_%"]]
    st.dataframe(df_show, use_container_width=True)
    download_link(df_show, "custos_x_producao_consolidado.csv")

else:
    st.warning("Sem interseção suficiente entre custos e produção para o período/seleção atual.")
