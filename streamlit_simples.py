import streamlit as st
import pandas as pd
import numpy as np
import altair as alt

st.set_page_config(page_title="FHEMIG | Custos × Produção — Versão Enxuta (colunas + linha)", layout="wide")

# ----------------------------------------------------
# Arquivos (primeira aba) — sem upload
# ----------------------------------------------------
CUSTOS_PATH = "dados_custos.xlsx"
PROD_PATH   = "dados_producao.xlsx"

try:
    df_costs_raw = pd.ExcelFile(CUSTOS_PATH).parse(0)  # primeira aba
    df_prod_raw  = pd.ExcelFile(PROD_PATH).parse(0)    # primeira aba
except Exception as e:
    st.error(
        "Não foi possível abrir os arquivos no diretório. "
        "Confirme se **dados_custos.xlsx** e **dados_producao.xlsx** estão na mesma pasta do app. "
        f"Detalhe: {e}"
    )
    st.stop()

# ----------------------------------------------------
# Helpers: meses PT-BR e números em formato BR
# ----------------------------------------------------
PT_MONTHS = {
    "janeiro": 1, "jan": 1,
    "fevereiro": 2, "fev": 2,
    "março": 3, "marco": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "maio": 5, "mai": 5,
    "junho": 6, "jun": 6,
    "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9, "sep": 9,
    "outubro": 10, "out": 10, "oct": 10,
    "novembro": 11, "nov": 11,
    "dezembro": 12, "dez": 12, "dec": 12
}

def normalize_month(m):
    if pd.isna(m): return np.nan
    s = str(m).strip().lower()
    # numérico direto
    try:
        v = int(float(s))
        if 1 <= v <= 12: return v
    except:
        pass
    return PT_MONTHS.get(s, np.nan)

def build_data_from_year_month(df, col_ano, col_mes):
    y = pd.to_numeric(df[col_ano], errors="coerce")
    m = df[col_mes].apply(normalize_month)
    dt = pd.to_datetime(dict(year=y, month=m, day=1), errors="coerce")
    return y, m, dt

def parse_br_number(x):
    """
    Converte strings como '4.743' -> 4743 ; '-919,21' -> -919.21
    Mantém números já numéricos.
    """
    if pd.isna(x):
        return np.nan
    if isinstance(x, (int, float, np.number)):
        return x
    s = str(x).strip()
    # remove espaços
    s = s.replace(" ", "")
    # se tiver vírgula, presume vírgula decimal
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        # sem vírgula: remover pontos de milhar
        # (ex.: '4.743' -> '4743')
        parts = s.split(".")
        if len(parts) > 1:
            s = "".join(parts)
    try:
        return float(s)
    except:
        return np.nan

def safediv(a, b):
    with np.errstate(divide='ignore', invalid='ignore'):
        out = np.true_divide(a, b)
        out[~np.isfinite(out)] = np.nan
    return out

# ----------------------------------------------------
# Adaptação de colunas para os nomes fornecidos
# ----------------------------------------------------
# Custos (Hospital | Competência - Ano | Competência - Mês | Grupo do item | Item de Custo | Valor)
cols_costs_needed = ["Hospital", "Competência - Ano", "Competência - Mês", "Grupo do item", "Item de Custo", "Valor"]
if not set(cols_costs_needed).issubset(df_costs_raw.columns):
    st.error("A planilha de **custos** deve conter: " + ", ".join(cols_costs_needed))
    st.stop()

df_costs = df_costs_raw[cols_costs_needed].rename(columns={
    "Competência - Ano": "Ano",
    "Competência - Mês": "Mes",
    "Grupo do item": "Grupo",
    "Item de Custo": "Item"
}).copy()

# números em formato BR (Valor)
df_costs["Valor"] = df_costs["Valor"].apply(parse_br_number)

# cria Data
df_costs["Ano"], df_costs["Mes"], df_costs["Data"] = build_data_from_year_month(df_costs, "Ano", "Mes")
df_costs = df_costs.dropna(subset=["Hospital", "Ano", "Mes", "Valor", "Data"])

# Produção (Estabelecimento | data - Ano | data - Mês | métricas ...)
cols_prod_min = ["Estabelecimento", "data - Ano", "data - Mês"]
if not set(cols_prod_min).issubset(df_prod_raw.columns):
    st.error("A planilha de **produção** deve conter: Estabelecimento, data - Ano, data - Mês + métricas.")
    st.stop()

df_prod = df_prod_raw.rename(columns={
    "Estabelecimento": "Hospital",
    "data - Ano": "Ano",
    "data - Mês": "Mes"
}).copy()

# converte métricas: remover pontos de milhar (e vírgula decimal se aparecer)
for c in df_prod.columns:
    if c not in ["Hospital", "Ano", "Mes"]:
        df_prod[c] = df_prod[c].apply(parse_br_number)

# cria Data
df_prod["Ano"], df_prod["Mes"], df_prod["Data"] = build_data_from_year_month(df_prod, "Ano", "Mes")
df_prod = df_prod.dropna(subset=["Hospital", "Ano", "Mes", "Data"])

# métricas disponíveis (numéricas, exceto Ano/Mes)
metric_candidates = [c for c in df_prod.select_dtypes(include="number").columns if c not in ["Ano", "Mes"]]
if not metric_candidates:
    st.error("Nenhuma métrica numérica de produção encontrada.")
    st.stop()

# ----------------------------------------------------
# Filtros
# ----------------------------------------------------
st.sidebar.header("🔎 Filtros")

hosp_all = sorted(set(df_costs["Hospital"]) | set(df_prod["Hospital"]))
sel_hosp = st.sidebar.multiselect("Hospitais", hosp_all, default=hosp_all)

grupos = ["(Todos)"] + sorted(df_costs["Grupo"].dropna().unique().tolist())
sel_grupo = st.sidebar.selectbox("Grupo de despesa", grupos, index=0)

metric_sel = st.sidebar.selectbox("Indicador de produção", metric_candidates, index=0)

# aplica filtros separados
costs_f = df_costs[df_costs["Hospital"].isin(sel_hosp)].copy()
if sel_grupo != "(Todos)":
    costs_f = costs_f[costs_f["Grupo"] == sel_grupo]

prod_f = df_prod[df_prod["Hospital"].isin(sel_hosp)].copy()

# ----------------------------------------------------
# Agregações por Hospital/Ano/Mes e MERGE direto
# ----------------------------------------------------
costs_m = (costs_f.groupby(["Hospital", "Ano", "Mes"], as_index=False)["Valor"].sum())

prod_m = (prod_f.groupby(["Hospital", "Ano", "Mes"], as_index=False)[metric_sel]
               .sum()
               .rename(columns={metric_sel: "Producao"}))

df = pd.merge(costs_m, prod_m, on=["Hospital", "Ano", "Mes"], how="inner")
df["Data"] = pd.to_datetime(dict(year=df["Ano"], month=df["Mes"], day=1), errors="coerce")
df = df.dropna(subset=["Data"]).sort_values(["Hospital", "Data"])

if df.empty:
    st.warning("Sem interseção entre custos e produção após filtros. Ajuste os filtros.")
    st.stop()

# Período (após merge)
min_date, max_date = df["Data"].min(), df["Data"].max()
date_range = st.sidebar.slider(
    "Período",
    min_value=min_date.to_pydatetime(),
    max_value=max_date.to_pydatetime(),
    value=(min_date.to_pydatetime(), max_date.to_pydatetime()),
    format="MM/YYYY"
)
df = df[(df["Data"] >= pd.to_datetime(date_range[0])) & (df["Data"] <= pd.to_datetime(date_range[1]))]
if df.empty:
    st.warning("Sem dados no intervalo selecionado.")
    st.stop()

# ----------------------------------------------------
# Header
# ----------------------------------------------------
st.title("🏥 FHEMIG — Custos × Produção (enxuto: colunas + linha)")
st.caption("Bases com colunas já equivalentes. Merge direto por Hospital/Ano/Mês.")

col1, col2, col3 = st.columns(3)
col1.metric("Hospitais", f"{len(sel_hosp)}")
col2.metric("Período", f"{date_range[0].strftime('%m/%Y')} – {date_range[1].strftime('%m/%Y')}")
col3.metric("Grupo", sel_grupo)

# ----------------------------------------------------
# Visualização 1 — Barras (Custo) + Linha (Produção) com 2 eixos Y
# ----------------------------------------------------
st.subheader("Custo × Produção (barras + linha, eixos independentes)")

# Agrega (somando hospitais filtrados) por competência
df_cols = (
    df.groupby("Data", as_index=False)
      .agg(Valor=("Valor", "sum"), Producao=("Producao", "sum"))
      .sort_values("Data")
)

base_x = alt.X("yearmonth(Data):T", title="Competência")

bar_custo = (
    alt.Chart(df_cols)
    .mark_bar(opacity=0.6)
    .encode(
        x=base_x,
        y=alt.Y("Valor:Q", axis=alt.Axis(title="Custo total (R$)")),
        tooltip=[
            alt.Tooltip("yearmonth(Data):T", title="Competência"),
            alt.Tooltip("Valor:Q", title="Custo (R$)")
        ]
    )
)

line_prod = (
    alt.Chart(df_cols)
    .mark_line(size=2, point=True)
    .encode(
        x=base_x,
        y=alt.Y("Producao:Q", axis=alt.Axis(title=f"Produção ({metric_sel})", orient="right")),
        tooltip=[
            alt.Tooltip("yearmonth(Data):T", title="Competência"),
            alt.Tooltip("Producao:Q", title=f"Produção ({metric_sel})")
        ]
    )
)

combo = alt.layer(bar_custo, line_prod).resolve_scale(y="independent").properties(height=360).interactive()
st.altair_chart(combo, use_container_width=True)


# ----------------------------------------------------
# Visualização 2 — Linha de eficiência (Custo / Produção)
# ----------------------------------------------------
st.subheader(f"Linha: Custo por {metric_sel} (eficiência)")

df_eff = df_cols.copy()
df_eff["Custo_por_Unidade"] = safediv(df_eff["Valor"], df_eff["Producao"])

st.altair_chart(
    alt.Chart(df_eff).mark_line(point=True).encode(
        x=alt.X("yearmonth(Data):T", title="Competência"),
        y=alt.Y("Custo_por_Unidade:Q", title=f"Custo por {metric_sel} (R$)"),
        tooltip=[alt.Tooltip("yearmonth(Data):T", title="Competência"),
                 alt.Tooltip("Custo_por_Unidade:Q", title=f"Custo por {metric_sel} (R$)")]
    ).properties(height=300).interactive(),
    use_container_width=True
)

# Texto interpretativo
if len(df_eff) >= 2 and df_eff["Custo_por_Unidade"].notna().any():
    ult2 = df_eff.sort_values("Data").tail(2)
    if ult2["Custo_por_Unidade"].notna().all():
        delta = ult2["Custo_por_Unidade"].iloc[-1] - ult2["Custo_por_Unidade"].iloc[0]
        sinal = "melhora" if delta < 0 else ("piora" if delta > 0 else "estabilidade")
        st.caption(
            f"No comparativo do último mês vs anterior, houve **{sinal}** de eficiência "
            f"(Δ custo/unidade = {delta:,.2f} R$)".replace(",", "X").replace(".", ",").replace("X",".")
        )
else:
    st.caption("Aguardando pelo menos duas competências válidas para comparar a eficiência mês a mês.")
