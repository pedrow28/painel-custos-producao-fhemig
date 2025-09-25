import numpy as np
import pandas as pd
import streamlit as st
import altair as alt

st.set_page_config(page_title="FHEMIG | Custos × Produção — Nominal vs IPCA (python-bcb)", layout="wide")

# ----------------------------------------------------
# Arquivos (primeira aba) — sem upload/sem abas
# ----------------------------------------------------
CUSTOS_XLS = "dados_custos.xlsx"
PROD_XLS   = "dados_producao.xlsx"

try:
    df_costs_raw = pd.ExcelFile(CUSTOS_XLS).parse(0)  # primeira aba
    df_prod_raw  = pd.ExcelFile(PROD_XLS).parse(0)    # primeira aba
except Exception as e:
    st.error(
        "Não foi possível abrir os arquivos no diretório. "
        "Confirme se **dados_custos.xlsx** e **dados_producao.xlsx** estão na mesma pasta do app. "
        f"Detalhe: {e}"
    )
    st.stop()

# ----------------------------------------------------
# Helpers
# ----------------------------------------------------
PT_MONTHS = {
    "janeiro":1, "jan":1, "fevereiro":2, "fev":2, "março":3, "marco":3, "mar":3,
    "abril":4, "abr":4, "maio":5, "mai":5, "junho":6, "jun":6, "julho":7, "jul":7,
    "agosto":8, "ago":8, "setembro":9, "set":9, "sep":9, "outubro":10, "out":10, "oct":10,
    "novembro":11, "nov":11, "dezembro":12, "dez":12, "dec":12
}

def to_month(m):
    if pd.isna(m): return np.nan
    s = str(m).strip().lower()
    try:
        v = int(float(s))
        if 1 <= v <= 12: return v
    except:
        pass
    return PT_MONTHS.get(s, np.nan)

def parse_br_number(x):
    """Converte formatos pt-BR:
       '4.743'->4743 ; '-919,21'->-919.21 ; números permanecem como estão."""
    if pd.isna(x): return np.nan
    if isinstance(x,(int,float,np.number)): return float(x)
    s = str(x).strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        return float(s)
    except:
        return np.nan

def safediv(a, b):
    with np.errstate(divide='ignore', invalid='ignore'):
        out = np.true_divide(a, b)
        out[~np.isfinite(out)] = np.nan
    return out

def fmt_br(v, nd=0, prefix=""):
    if pd.isna(v):
        return ""
    try:
        s = f"{float(v):,.{nd}f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{prefix}{s}"
    except Exception:
        return ""

# ----------------------------------------------------
# IPCA (python-bcb/SGS) — correção do RangeIndex
# ----------------------------------------------------
@st.cache_data(show_spinner=False)
def fetch_ipca_bcb(dt_start, dt_end):
    """
    Busca IPCA mensal no SGS/BCB via python-bcb.
    Série 433 = IPCA (variação mensal, %).
    Retorna: DataFrame com colunas ['Data','ipca_var_pct','ipca_indice'].
    """
    try:
        from bcb import sgs  # pip install python-bcb
    except Exception:
        return None, "Pacote 'python-bcb' não encontrado. Instale com: pip install python-bcb"

    try:
        # Aceita tupla (nome, código) — documentação oficial:
        # https://wilsonfreitas.github.io/python-bcb/sgs.html
        ipca = sgs.get(("ipca_var_pct", 433),
                       start=pd.to_datetime(dt_start).strftime("%Y-%m-%d"),
                       end=pd.to_datetime(dt_end).strftime("%Y-%m-%d"))
        # Vem com DatetimeIndex nomeado "Date"
        ipca = ipca.reset_index()                 # coluna "Date"
        ipca = ipca.rename(columns={"Date": "Data"})
        # Garante alinhamento mensal no 1º dia do mês
        ipca["Data"] = pd.to_datetime(ipca["Data"]).dt.to_period("M").dt.to_timestamp()
        ipca = ipca.sort_values("Data")
        # Índice acumulado de preços (base livre; rebase faremos depois)
        ipca["ipca_indice"] = (1.0 + ipca["ipca_var_pct"] / 100.0).cumprod()
        return ipca[["Data", "ipca_var_pct", "ipca_indice"]], None

    except Exception as e:
        return None, f"Falha ao consultar IPCA via python-bcb/SGS: {e}"


# ----------------------------------------------------
# Adaptação de colunas (de acordo com suas planilhas)
# ----------------------------------------------------
# Custos: Hospital | Competência - Ano | Competência - Mês | Grupo do item | Item de Custo | Valor
req_costs = ["Hospital","Competência - Ano","Competência - Mês","Grupo do item","Item de Custo","Valor"]
if not set(req_costs).issubset(df_costs_raw.columns):
    st.error("Planilha de **custos** deve conter: " + ", ".join(req_costs))
    st.stop()

df_costs = df_costs_raw[req_costs].rename(columns={
    "Competência - Ano":"Ano",
    "Competência - Mês":"Mes",
    "Grupo do item":"Grupo",
    "Item de Custo":"Item"
}).copy()
df_costs["Ano"]   = pd.to_numeric(df_costs["Ano"], errors="coerce")
df_costs["Mes"]   = df_costs["Mes"].apply(to_month)
df_costs["Valor"] = df_costs["Valor"].apply(parse_br_number)
df_costs = df_costs.dropna(subset=["Hospital","Ano","Mes","Valor"])
df_costs["Data"] = pd.to_datetime(dict(year=df_costs["Ano"], month=df_costs["Mes"], day=1), errors="coerce")
df_costs = df_costs.dropna(subset=["Data"])

# Produção: Estabelecimento | data - Ano | data - Mês | métricas
req_prod_min = ["Estabelecimento","data - Ano","data - Mês"]
if not set(req_prod_min).issubset(df_prod_raw.columns):
    st.error("Planilha de **produção** deve conter: Estabelecimento, data - Ano, data - Mês + métricas.")
    st.stop()

df_prod = df_prod_raw.rename(columns={
    "Estabelecimento":"Hospital",
    "data - Ano":"Ano",
    "data - Mês":"Mes"
}).copy()
df_prod["Ano"] = pd.to_numeric(df_prod["Ano"], errors="coerce")
df_prod["Mes"] = df_prod["Mes"].apply(to_month)
for c in df_prod.columns:
    if c not in ["Hospital","Ano","Mes"]:
        df_prod[c] = df_prod[c].apply(parse_br_number)
df_prod = df_prod.dropna(subset=["Hospital","Ano","Mes"])
df_prod["Data"] = pd.to_datetime(dict(year=df_prod["Ano"], month=df_prod["Mes"], day=1), errors="coerce")
df_prod = df_prod.dropna(subset=["Data"])

# Métricas de produção (numéricas)
metric_candidates = [c for c in df_prod.select_dtypes(include=["number"]).columns if c not in ["Ano","Mes"]]
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

ajuste_preco = st.sidebar.radio(
    "Série de preços",
    ["Nominal", "Deflacionado (IPCA/BCB)"],
    horizontal=True,
    index=0
)

# Filtra bases
costs_f = df_costs[df_costs["Hospital"].isin(sel_hosp)].copy()
if sel_grupo != "(Todos)":
    costs_f = costs_f.loc[costs_f["Grupo"] == sel_grupo]

prod_f = df_prod[df_prod["Hospital"].isin(sel_hosp)].copy()

# Interseção de datas para o slider
min_date = max(costs_f["Data"].min(), prod_f["Data"].min())
max_date = min(costs_f["Data"].max(), prod_f["Data"].max())
date_range = st.sidebar.slider(
    "Período",
    min_value=min_date.to_pydatetime(),
    max_value=max_date.to_pydatetime(),
    value=(min_date.to_pydatetime(), max_date.to_pydatetime()),
    format="MM/YYYY"
)

# Aplica período
costs_f = costs_f[(costs_f["Data"] >= pd.to_datetime(date_range[0])) & (costs_f["Data"] <= pd.to_datetime(date_range[1]))]
prod_f  = prod_f[(prod_f["Data"]  >= pd.to_datetime(date_range[0])) & (prod_f["Data"]  <= pd.to_datetime(date_range[1]))]

# ----------------------------------------------------
# Agregações e MERGE (Hospital/Ano/Mes)
# ----------------------------------------------------
costs_m = (costs_f.groupby(["Hospital","Ano","Mes","Data"], as_index=False)["Valor"].sum())
prod_m  = (prod_f.groupby(["Hospital","Ano","Mes","Data"], as_index=False)[metric_sel]
                .sum()
                .rename(columns={metric_sel:"Producao"}))

df = pd.merge(costs_m, prod_m, on=["Hospital","Ano","Mes","Data"], how="inner").sort_values(["Hospital","Data"])
if df.empty:
    st.warning("Sem interseção entre custos e produção após filtros/período.")
    st.stop()

# Agregado (somando hospitais filtrados) para visualização
df_cols = (df.groupby("Data", as_index=False)
             .agg(Valor=("Valor","sum"), Producao=("Producao","sum"))
             .sort_values("Data"))


# ----------------------------------------------------
# IPCA opcional (deflação via python-bcb)
# ----------------------------------------------------
ipca_df = None
ipca_msg = None
if ajuste_preco == "Deflacionado (IPCA/BCB)":
    ipca_df, ipca_msg = fetch_ipca_bcb(df_cols["Data"].min(), df_cols["Data"].max())
    if ipca_df is None:
        st.warning(f"Não foi possível aplicar IPCA agora. Motivo: {ipca_msg}. Exibindo valores **nominais**.")
        ajuste_preco = "Nominal"

# Se deflacionado, ajusta custo: rebase índice no **último mês do período** (=1.0)
if ajuste_preco == "Deflacionado (IPCA/BCB)" and ipca_df is not None:
    df_cols_ipca = pd.merge(df_cols, ipca_df[["Data","ipca_indice"]], on="Data", how="left").sort_values("Data")
    ind_last = df_cols_ipca["ipca_indice"].dropna().iloc[-1]
    df_cols_ipca["ind_rebased"] = df_cols_ipca["ipca_indice"] / ind_last
    df_cols_ipca["Valor_ajustado"] = safediv(df_cols_ipca["Valor"], df_cols_ipca["ind_rebased"])
    df_cols_plot = df_cols_ipca
    legenda_custo = "Custo deflacionado (R$ de mês mais recente)"
    st.caption("**Nota (IPCA)**: Valores deflacionados para o **mês mais recente do período** usando IPCA/BCB (SGS-433).")
else:
    df_cols_plot = df_cols.copy()
    df_cols_plot["Valor_ajustado"] = df_cols_plot["Valor"]
    legenda_custo = "Custo nominal (R$)"

# -------------------------------------------
# IPCA acumulado no período selecionado
# -------------------------------------------
ipca_acum_txt = "—"  # default quando não houver IPCA

if (ajuste_preco == "Deflacionado (IPCA/BCB)") and (ipca_df is not None) and (not ipca_df.empty):
    # Usa as datas já filtradas do agregado (df_cols_plot)
    dt_min = df_cols_plot["Data"].min()
    dt_max = df_cols_plot["Data"].max()

    ipca_per = ipca_df[(ipca_df["Data"] >= dt_min) & (ipca_df["Data"] <= dt_max)].copy()
    ipca_per = ipca_per.dropna(subset=["ipca_indice"]).sort_values("Data")

    if not ipca_per.empty:
        ind_first = ipca_per["ipca_indice"].iloc[0]
        ind_last  = ipca_per["ipca_indice"].iloc[-1]
        if pd.notna(ind_first) and pd.notna(ind_last) and ind_first != 0:
            ipca_acum = (ind_last / ind_first - 1.0) * 100.0
            ipca_acum_txt = f"{ipca_acum:.1f}%"


# ----------------------------------------------------
# Cabeçalho
# ----------------------------------------------------
# ----------------------------------------------------
# Cabeçalho
# ----------------------------------------------------
st.title("🏥 FHEMIG — Custos × Produção")
st.caption(
    "Visualização executiva com opção de **ajuste por inflação (IPCA/BCB via python-bcb)**. "
    "A linha de **produção** é destacada para facilitar a comparação."
)

c1, c2, c3 = st.columns(3)
c1.metric("Hospitais", f"{len(sel_hosp)}")
c2.metric("Período", f"{date_range[0].strftime('%m/%Y')} – {date_range[1].strftime('%m/%Y')}")
c3.metric("IPCA acumulado no período", ipca_acum_txt, help=(
    "Variação acumulada do IPCA no intervalo selecionado. "
    "Calculada a partir da série 433 (var. mensal %), com índice cumulativo."
))


# ----------------------------------------------------
# Visualização 1 — Barras (Custo) + Linha (Produção), 2 eixos Y
# ----------------------------------------------------
st.subheader("Custo × Produção — Barras (Custo) + Linha (Produção)")

base_x = alt.X("yearmonth(Data):T", title="Competência")

bar_custo = (
    alt.Chart(df_cols_plot)
    .mark_bar(opacity=0.6)
    .encode(
        x=base_x,
        y=alt.Y("Valor_ajustado:Q", axis=alt.Axis(title=legenda_custo)),
        tooltip=[
            alt.Tooltip("yearmonth(Data):T", title="Competência"),
            alt.Tooltip("Valor_ajustado:Q", title=legenda_custo, format=",.0f"),
        ]
    )
)

line_prod = (
    alt.Chart(df_cols_plot)
    .mark_line(size=3)
    .encode(
        x=base_x,
        y=alt.Y("Producao:Q", axis=alt.Axis(title=f"Produção ({metric_sel})", orient="right")),
        color=alt.value("#e61919"),
        tooltip=[
            alt.Tooltip("yearmonth(Data):T", title="Competência"),
            alt.Tooltip("Producao:Q", title=f"Produção ({metric_sel})", format=",.0f"),
        ]
    )
) + alt.Chart(df_cols_plot).mark_point(size=50, filled=True, color="#e61919").encode(
    x=base_x, y="Producao:Q"
)

combo = alt.layer(bar_custo, line_prod).resolve_scale(y="independent").properties(height=380).interactive()
st.altair_chart(combo, use_container_width=True)


# ----------------------------------------------------
# Visualização 2 — Linha de eficiência (Custo / Produção)
# ----------------------------------------------------
st.subheader(f"Eficiência — Custo por {metric_sel}")

df_eff = df_cols_plot.copy()
df_eff["Custo_por_Unid"] = safediv(df_eff["Valor_ajustado"], df_eff["Producao"])

st.altair_chart(
    alt.Chart(df_eff).mark_line(point=True).encode(
        x=alt.X("yearmonth(Data):T", title="Competência"),
        y=alt.Y("Custo_por_Unid:Q", axis=alt.Axis(title=f"Custo por {metric_sel} (R$)")),
        tooltip=[alt.Tooltip("yearmonth(Data):T", title="Competência"),
                 alt.Tooltip("Custo_por_Unid:Q", title=f"Custo por {metric_sel} (R$)", format=",.2f")]
    ).properties(height=320).interactive(),
    use_container_width=True
)

# ----------------------------------------------------
# Tabela executiva por hospital — Variação nominal e real
# ----------------------------------------------------
st.subheader("Resumo por hospital — Variação no período (nominal e real)")

df_h = df.copy()[["Hospital","Data","Valor","Producao"]].sort_values(["Hospital","Data"])

# Ajuste real por IPCA (rebase no último mês por hospital)
if ajuste_preco == "Deflacionado (IPCA/BCB)" and ipca_df is not None:
    aux = pd.merge(df_h, ipca_df[["Data","ipca_indice"]], on="Data", how="left").sort_values(["Hospital","Data"])
    # rebase por hospital no último registro disponível
    def last_nonnull(s):
        s = s.dropna()
        return s.iloc[-1] if len(s) else np.nan
    ind_last_by_h = aux.groupby("Hospital")["ipca_indice"].transform(last_nonnull)
    aux["ind_rebased"] = safediv(aux["ipca_indice"], ind_last_by_h)
    aux["Valor_real"]  = safediv(aux["Valor"], aux["ind_rebased"])
else:
    aux = df_h.copy()
    aux["Valor_real"] = np.nan

# pega primeiro/último válidos
def first_valid(s): 
    s = s.dropna()
    return s.iloc[0] if len(s) else np.nan

def last_valid(s):
    s = s.dropna()
    return s.iloc[-1] if len(s) else np.nan

res = (aux.groupby("Hospital")
          .agg(
              Custo_nominal_ini=("Valor", first_valid),
              Custo_nominal_fim=("Valor", last_valid),
              Producao_ini=("Producao", first_valid),
              Producao_fim=("Producao", last_valid),
              Custo_real_ini=("Valor_real", first_valid),
              Custo_real_fim=("Valor_real", last_valid),
          )
          .reset_index())

res["Var_nominal_%"] = safediv(res["Custo_nominal_fim"] - res["Custo_nominal_ini"], res["Custo_nominal_ini"]) * 100
if ajuste_preco == "Deflacionado (IPCA/BCB)" and ipca_df is not None:
    res["Var_real_%"] = safediv(res["Custo_real_fim"] - res["Custo_real_ini"], res["Custo_real_ini"]) * 100
else:
    res["Var_real_%"] = np.nan

res["Var_producao_%"] = safediv(res["Producao_fim"] - res["Producao_ini"], res["Producao_ini"]) * 100

ord_col = "Var_real_%" if (ajuste_preco == "Deflacionado (IPCA/BCB)" and ipca_df is not None) else "Var_nominal_%"
res = res.sort_values(ord_col, ascending=False)

# Formatação
res_show = res.copy()
for c in ["Custo_nominal_ini","Custo_nominal_fim","Custo_real_ini","Custo_real_fim","Producao_ini","Producao_fim"]:
    if c in res_show.columns:
        res_show[c] = res_show[c].apply(lambda v: "-" if pd.isna(v) else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
for c in ["Var_nominal_%","Var_real_%","Var_producao_%"]:
    res_show[c] = res_show[c].apply(lambda v: "-" if pd.isna(v) else f"{v:.1f}%")

# Renomeia cabeçalhos para nomes legíveis
rename_cols = {
    "Hospital": "Hospital",
    "Custo_nominal_ini": "Custo nominal (início)",
    "Custo_nominal_fim": "Custo nominal (fim)",
    "Var_nominal_%": "Variação nominal (%)",
    "Custo_real_ini": "Custo real (início)",
    "Custo_real_fim": "Custo real (fim)",
    "Var_real_%": "Variação real (%)",
    "Producao_ini": f"Produção (início) — {metric_sel}",
    "Producao_fim": f"Produção (fim) — {metric_sel}",
    "Var_producao_%": "Variação da produção (%)"
}
res_show = res_show.rename(columns=rename_cols)

cols_order = [
    "Hospital",
    "Custo nominal (início)","Custo nominal (fim)","Variação nominal (%)",
    "Custo real (início)","Custo real (fim)","Variação real (%)",
    f"Produção (início) — {metric_sel}", f"Produção (fim) — {metric_sel}", "Variação da produção (%)"
]

st.dataframe(res_show[cols_order], use_container_width=True)

st.markdown(
    "> **Notas**: "
    "- *Variação nominal* compara custos sem ajuste de preços. "
    "- *Variação real* deflaciona os custos pelo **IPCA mensal acumulado** (SGS 433), "
    "re-escalado para o **mês mais recente** do período. "
    "A produção não é deflacionada."
)


st.markdown("---")
st.markdown(
    "**Metodologia**: O IPCA utilizado é a **série 433 (variação mensal, %)** do SGS/BCB, "
    "consultada via **python-bcb** (`bcb.sgs.get`). O índice real é calculado por "
    "`(1 + var/100)` **cumulativo** e reescalado para 1,0 no último mês do período; "
    "o custo real é `Custo_nominal / índice_rebase`. A eficiência é `Custo / Produção`. "
    "Os eixos dos gráficos são independentes."
)
