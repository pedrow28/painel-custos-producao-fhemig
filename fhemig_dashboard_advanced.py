
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from io import BytesIO
from scipy.stats import pearsonr, spearmanr, zscore
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from statsmodels.tsa.seasonal import seasonal_decompose

st.set_page_config(page_title="FHEMIG | Dashboard Analítico Custos × Produção", layout="wide")

# =====================================
# Utils & Helpers
# =====================================

PT_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}
MONTH_LABELS = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]

def normalize_month(m):
    if pd.isna(m):
        return np.nan
    s = str(m).strip().lower()
    try:
        v = int(float(s))
        if 1 <= v <= 12:
            return v
    except:
        pass
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

def safediv(a, b):
    with np.errstate(divide='ignore', invalid='ignore'):
        out = np.true_divide(a, b)
        out[~np.isfinite(out)] = np.nan
    return out

def corr_stats(x, y, method="pearson"):
    x = pd.Series(x).astype(float)
    y = pd.Series(y).astype(float)
    mask = x.notna() & y.notna()
    if mask.sum() < 3:
        return np.nan, np.nan
    if method == "spearman":
        r, p = spearmanr(x[mask], y[mask])
    else:
        r, p = pearsonr(x[mask], y[mask])
    return float(r), float(p)

def regression_stats(x, y):
    x = pd.Series(x).astype(float)
    y = pd.Series(y).astype(float)
    mask = x.notna() & y.notna()
    if mask.sum() < 3:
        return None
    X = x[mask].values.reshape(-1,1)
    Y = y[mask].values.reshape(-1,1)
    model = LinearRegression().fit(X, Y)
    pred = model.predict(X)
    r2 = r2_score(Y, pred)
    slope = model.coef_[0][0]
    intercept = model.intercept_[0]
    return {"r2": float(r2), "slope": float(slope), "intercept": float(intercept), "n": int(mask.sum())}

def iqr_outliers(series, k=1.5):
    s = pd.Series(series).astype(float).dropna()
    if s.empty:
        return pd.Series([False]*len(series), index=series.index)
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - k*iqr, q3 + k*iqr
    return (series < lower) | (series > upper)

def download_button_df(df, filename, label="Baixar (Excel)"):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="dados")
    buffer.seek(0)
    st.download_button(label, data=buffer, file_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@st.cache_data(show_spinner=False)
def load_excel(_xfile, sheet_name):  # <— o "_" evita o hash desse arg
    # funciona tanto se você passar um ExcelFile quanto um caminho (str)
    if isinstance(_xfile, pd.ExcelFile):
        return _xfile.parse(sheet_name)
    else:
        return pd.read_excel(_xfile, sheet_name=sheet_name)


@st.cache_data(show_spinner=False)
def parse_costs(df_costs_raw):
    COSTS_COLS = {
        "Hospital": ["Hospital","Estabelecimento","Unidade","Unidade/Hospital"],
        "Ano": ["Competência - Ano","Ano","data - Ano","Ano Competência"],
        "Mes": ["Competência - Mês","Mês","data - Mês","Mes Competência"],
        "Grupo": ["Grupo do item","Grupo do Item","Grupo","Grupo de Despesa"],
        "Item": ["Item de Custo","Item","Item de custo"],
        "Valor": ["Valor","Valor (R$)","Valor Total"]
    }
    def pick(df, names): 
        for n in names:
            if n in df.columns: return n
        return None
    c_hosp = pick(df_costs_raw, COSTS_COLS["Hospital"])
    c_ano  = pick(df_costs_raw, COSTS_COLS["Ano"])
    c_mes  = pick(df_costs_raw, COSTS_COLS["Mes"])
    c_grp  = pick(df_costs_raw, COSTS_COLS["Grupo"])
    c_item = pick(df_costs_raw, COSTS_COLS["Item"])
    c_val  = pick(df_costs_raw, COSTS_COLS["Valor"])
    missing = [n for n,v in {
        "Custos: Hospital": c_hosp, "Custos: Ano": c_ano, "Custos: Mês": c_mes, "Custos: Grupo": c_grp, "Custos: Item": c_item, "Custos: Valor": c_val
    }.items() if v is None]
    if missing:
        st.error("Colunas obrigatórias de custos não encontradas: " + ", ".join(missing))
        st.stop()
    df = df_costs_raw[[c_hosp, c_ano, c_mes, c_grp, c_item, c_val]].copy()
    df.columns = ["Hospital","Ano","Mes","Grupo","Item","Valor"]
    df["Ano"], df["Mes"], df["Data"] = build_year_month(df, "Ano","Mes")
    df["Valor"] = pd.to_numeric(df["Valor"], errors="coerce")
    df = df.dropna(subset=["Hospital","Ano","Mes","Data","Valor"])
    df = df.groupby(["Hospital","Ano","Mes","Data","Grupo","Item"], as_index=False)["Valor"].sum()
    return df

@st.cache_data(show_spinner=False)
def parse_prod(df_prod_raw):
    PROD_COLS = {
        "Hospital": ["Estabelecimento","Hospital","Unidade","Unidade/Hospital"],
        "Ano": ["data - Ano","Ano","Competência - Ano"],
        "Mes": ["data - Mês","Mês","Competência - Mês"],
    }
    def pick(df, names): 
        for n in names:
            if n in df.columns: return n
        return None
    p_hosp = pick(df_prod_raw, PROD_COLS["Hospital"])
    p_ano  = pick(df_prod_raw,  PROD_COLS["Ano"])
    p_mes  = pick(df_prod_raw,  PROD_COLS["Mes"])
    missing = [n for n,v in {"Prod: Hospital": p_hosp, "Prod: Ano": p_ano, "Prod: Mês": p_mes}.items() if v is None]
    if missing:
        st.error("Colunas obrigatórias de produção não encontradas: " + ", ".join(missing))
        st.stop()
    df = df_prod_raw.copy()
    # --- dentro de parse_prod, logo após df = df_prod_raw.copy() ---
    # Renomeia apenas as três chaves, mantendo o resto igual
    df = df.rename(columns={p_hosp: "Hospital", p_ano: "Ano", p_mes: "Mes"})

    # Reordena para deixar as chaves na frente (opcional)
    other_cols = [c for c in df.columns if c not in ["Hospital", "Ano", "Mes"]]
    df = df[["Hospital", "Ano", "Mes"] + other_cols]
    # --- dentro de parse_prod, logo após:
# df = df.rename(columns={p_hosp: "Hospital", p_ano: "Ano", p_mes: "Mes"})
# other_cols = [c for c in df.columns if c not in ["Hospital", "Ano", "Mes"]]
# df = df[["Hospital", "Ano", "Mes"] + other_cols]

    # (re)constrói Ano/Mes/Data de forma explícita
    df["Ano"] = df["Ano"].apply(make_year_int)
    df["Mes"] = df["Mes"].apply(normalize_month)
    df["Data"] = pd.to_datetime(
        dict(year=df["Ano"], month=df["Mes"], day=1),
        errors="coerce"
    )

    # mantém apenas linhas válidas
    df = df.dropna(subset=["Hospital", "Ano", "Mes", "Data"])

    # garante que as métricas restantes sejam numéricas
    for c in df.columns:
        if c not in ["Hospital", "Ano", "Mes", "Data"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df



def slice_quarter(dt):
    return (dt.dt.month.sub(1)//3 + 1).astype("Int64")

def altair_logo_chart(chart, height=300):
    return chart.properties(height=height).interactive()

# =====================================
# Sidebar - Data
# =====================================

st.sidebar.header("📦 Dados de entrada")

# Caminhos fixos no diretório do projeto
default_costs_path = "dados_custos.xlsx"       # exatamente como está na pasta
default_prod_path  = "dados_producao.xlsx"     # exatamente como está na pasta

# Abre diretamente os arquivos do diretório
try:
    costs_xls = pd.ExcelFile(default_costs_path)
    prod_xls  = pd.ExcelFile(default_prod_path)
except Exception as e:
    st.sidebar.error("Erro ao abrir arquivos. Verifique se 'dados_custos.xlsx' e 'dados_producao.xlsx' estão na mesma pasta do app.")
    st.stop()

# Seleciona abas
costs_sheet = st.sidebar.selectbox("Aba de custos", costs_xls.sheet_names, index=0)
prod_sheet  = st.sidebar.selectbox("Aba de produção", prod_xls.sheet_names, index=0)

# Carrega os dados
df_costs_raw = load_excel(costs_xls, costs_sheet)
df_prod_raw  = load_excel(prod_xls,  prod_sheet)

df_costs = parse_costs(df_costs_raw)
df_prod  = parse_prod(df_prod_raw)


# =====================================
# Sidebar - Filtros
# =====================================

st.sidebar.header("🔎 Filtros")
hospitais = sorted(set(df_costs["Hospital"].unique()).union(set(df_prod["Hospital"].unique())))
sel_hosp = st.sidebar.multiselect("Hospitais", hospitais, default=hospitais)

min_date = max(df_costs["Data"].min(), df_prod["Data"].min())
max_date = min(df_costs["Data"].max(), df_prod["Data"].max())
date_range = st.sidebar.slider("Período", min_value=min_date.to_pydatetime(), max_value=max_date.to_pydatetime(),
                               value=(min_date.to_pydatetime(), max_date.to_pydatetime()), format="MM/YYYY")

with st.sidebar.expander("Filtros temporais avançados"):
    anos_disp = sorted(df_costs["Ano"].dropna().unique())
    sel_anos = st.multiselect("Anos", anos_disp, default=anos_disp)
    trimestres = [1,2,3,4]
    sel_tris = st.multiselect("Trimestres", trimestres, default=trimestres)
    meses = list(range(1,13))
    sel_meses = st.multiselect("Meses", meses, default=meses, format_func=lambda m: MONTH_LABELS[m-1])

grupos = ["(Todos)"] + sorted(df_costs["Grupo"].dropna().unique().tolist())
group_sel = st.sidebar.selectbox("Grupo de despesa", grupos, index=0)
if group_sel != "(Todos)":
    items = ["(Todos)"] + sorted(df_costs.loc[df_costs["Grupo"]==group_sel, "Item"].dropna().unique().tolist())
else:
    items = ["(Todos)"] + sorted(df_costs["Item"].dropna().unique().tolist())
item_sel = st.sidebar.selectbox("Item de custo", items, index=0)

metric_candidates = [c for c in df_prod.columns if c not in ["Hospital","Ano","Mes","Data"]]
metric_sel = st.sidebar.selectbox("Métrica de produção", metric_candidates, index=0)

alert_threshold = st.sidebar.slider("Limite de alerta (variação % absoluta)", 0, 200, 20)

# =====================================
# Filtragem base
# =====================================

mask_costs = (
    df_costs["Hospital"].isin(sel_hosp) &
    (df_costs["Data"] >= pd.to_datetime(date_range[0])) &
    (df_costs["Data"] <= pd.to_datetime(date_range[1])) &
    (df_costs["Ano"].isin(sel_anos)) &
    (df_costs["Mes"].isin(sel_meses))
)
if group_sel != "(Todos)":
    mask_costs &= (df_costs["Grupo"]==group_sel)
if item_sel != "(Todos)":
    mask_costs &= (df_costs["Item"]==item_sel)
dfc = df_costs.loc[mask_costs].copy()
dfc["Trimestre"] = slice_quarter(dfc["Data"])

mask_prod = (
    df_prod["Hospital"].isin(sel_hosp) &
    (df_prod["Data"] >= pd.to_datetime(date_range[0])) &
    (df_prod["Data"] <= pd.to_datetime(date_range[1])) &
    (df_prod["Ano"].isin(sel_anos)) &
    (df_prod["Mes"].isin(sel_meses))
)
dfp = df_prod.loc[mask_prod, ["Hospital","Ano","Mes","Data", metric_sel]].copy()
dfp["Trimestre"] = slice_quarter(dfp["Data"])
dfp.rename(columns={metric_sel: "Producao"}, inplace=True)

dfc_agg = dfc.groupby(["Hospital","Ano","Mes","Trimestre","Data"], as_index=False)["Valor"].sum()
dfp_agg = dfp.groupby(["Hospital","Ano","Mes","Trimestre","Data"], as_index=False)["Producao"].sum()

dfm = pd.merge(dfc_agg, dfp_agg, on=["Hospital","Ano","Mes","Trimestre","Data"], how="inner").sort_values(["Hospital","Data"])
dfm["Custo_por_Producao"] = safediv(dfm["Valor"], dfm["Producao"])

for col in ["Valor","Producao","Custo_por_Producao"]:
    dfm[f"Var_{col}_pct"] = dfm.groupby("Hospital")[col].pct_change() * 100.0

# =====================================
# Header & KPIs
# =====================================

st.title("🏥 FHEMIG — Dashboard Analítico: Custos × Produção")
st.caption("Análises gerenciais com correlação, regressão, sazonalidade, outliers e benchmarking.")

k1,k2,k3,k4 = st.columns(4)
k1.metric("Hospitais", f"{len(sel_hosp)}")
k2.metric("Período", f"{date_range[0].strftime('%m/%Y')} – {date_range[1].strftime('%m/%Y')}")
k3.metric("Custo total (R$)", f"{dfm['Valor'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
k4.metric(f"Total {metric_sel}", f"{dfm['Producao'].sum():,.0f}".replace(",", "X").replace(".", ",").replace("X","."))

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Tendências & Séries",
    "🔗 Correlação & Regressão",
    "📆 Sazonalidade & Outliers",
    "🏁 Benchmarking",
    "🧾 Relatórios & Exportação"
])

with tab1:
    st.subheader("Séries temporais")
    base = alt.Chart(dfm).encode(x=alt.X("yearmonth(Data):T", title="Competência"))
    st.altair_chart(altair_logo_chart(base.mark_line().encode(y=alt.Y("Valor:Q", title="Custo (R$)"), color="Hospital:N"), 320), use_container_width=True)
    st.altair_chart(altair_logo_chart(base.mark_line().encode(y=alt.Y("Producao:Q", title=f"Produção ({metric_sel})"), color="Hospital:N"), 320), use_container_width=True)

    st.markdown("#### Variações % (MoM)")
    var_long = dfm.melt(id_vars=["Hospital","Data"], value_vars=["Var_Valor_pct","Var_Producao_pct","Var_Custo_por_Producao_pct"],
                        var_name="Indicador", value_name="Variação %")
    mapn = {"Var_Valor_pct":"Custo (%)","Var_Producao_pct":"Produção (%)","Var_Custo_por_Producao_pct":"Custo/Produção (%)"}
    var_long["Indicador"] = var_long["Indicador"].map(mapn)
    st.altair_chart(
        alt.Chart(var_long).mark_line().encode(
            x=alt.X("yearmonth(Data):T", title="Competência"),
            y=alt.Y("Variação %:Q"),
            color="Indicador:N",
            facet=alt.Facet("Hospital:N", columns=1, title=None)
        ).properties(height=160),
        use_container_width=True
    )

    st.markdown("#### Heatmaps (sazonalidade por ano/mês)")
    dfm["AnoNum"] = dfm["Data"].dt.year.astype(int)
    dfm["MesNum"] = dfm["Data"].dt.month.astype(int)
    metric_heat = st.selectbox("Métrica para heatmap", ["Valor","Producao","Custo_por_Producao"], index=0)
    hm = alt.Chart(dfm).mark_rect().encode(
        x=alt.X("MesNum:O", title="Mês", axis=alt.Axis(labelExpr='["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"][datum.value-1]')),
        y=alt.Y("AnoNum:O", title="Ano"),
        color=alt.Color(f"{metric_heat}:Q", title=metric_heat.replace("_"," ")),
        facet=alt.Facet("Hospital:N", columns=1, title=None)
    ).properties(height=180)
    st.altair_chart(hm, use_container_width=True)

    st.markdown("#### Análise por Categoria (barras)")
    agg_dim = st.radio("Dimensão:", ["Grupo","Item"], horizontal=True)
    df_cat = dfc.copy()
    df_cat = df_cat.groupby(["Hospital", agg_dim], as_index=False)["Valor"].sum()
    bar = alt.Chart(df_cat).mark_bar().encode(
        x=alt.X("Valor:Q", title="Valor (R$)"),
        y=alt.Y(f"{agg_dim}:N", sort="-x"),
        color="Hospital:N",
        tooltip=["Hospital", agg_dim, "Valor"]
    ).facet(row="Hospital:N")
    st.altair_chart(bar, use_container_width=True)

with tab2:
    st.subheader("Dispersões e estatísticas")
    cor_method = st.radio("Método de correlação", ["pearson","spearman"], horizontal=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Níveis: Custo vs Produção**")
        st.altair_chart(
            alt.Chart(dfm).mark_circle(size=80, opacity=0.6).encode(
                x=alt.X("Valor:Q", title="Custo (R$)"),
                y=alt.Y("Producao:Q", title=f"Produção ({metric_sel})"),
                color="Hospital:N",
                tooltip=["Hospital","Data","Valor","Producao"]
            ) + alt.Chart(dfm).transform_regression("Valor","Producao").mark_line(),
            use_container_width=True
        )
    with c2:
        st.markdown("**Variações: Δ% Custo vs Δ% Produção**")
        dvt = dfm.dropna(subset=["Var_Valor_pct","Var_Producao_pct"])
        st.altair_chart(
            alt.Chart(dvt).mark_circle(size=80, opacity=0.6).encode(
                x=alt.X("Var_Valor_pct:Q", title="Δ% Custo"),
                y=alt.Y("Var_Producao_pct:Q", title="Δ% Produção"),
                color="Hospital:N",
                tooltip=["Hospital","Data","Var_Valor_pct","Var_Producao_pct"]
            ) + alt.Chart(dvt).transform_regression("Var_Valor_pct","Var_Producao_pct").mark_line(),
            use_container_width=True
        )

    r_lvl, p_lvl = corr_stats(dfm["Valor"], dfm["Producao"], method=cor_method)
    r_var, p_var = corr_stats(dfm["Var_Valor_pct"], dfm["Var_Producao_pct"], method=cor_method)
    reg_lvl = regression_stats(dfm["Valor"], dfm["Producao"])

    m1,m2,m3 = st.columns(3)
    m1.metric("Correlação (níveis)", f"{r_lvl:.3f}" if pd.notna(r_lvl) else "N/A", help=f"p-valor: {p_lvl:.4f}" if pd.notna(p_lvl) else "")
    m2.metric("Correlação (variações %)", f"{r_var:.3f}" if pd.notna(r_var) else "N/A", help=f"p-valor: {p_var:.4f}" if pd.notna(p_var) else "")
    if reg_lvl:
        m3.metric("Regressão (R² níveis)", f"{reg_lvl['r2']:.3f}", help=f"Equação: y = {reg_lvl['slope']:.4f}x + {reg_lvl['intercept']:.2f} (n={reg_lvl['n']})")
    else:
        m3.metric("Regressão (R² níveis)", "N/A")

    st.markdown("> **Interpretação rápida:** R² próximo de 1 indica que a produção é bem explicada pelos custos no modelo linear; p-valor < 0,05 sugere significância estatística.")

with tab3:
    st.subheader("Decomposição sazonal (aditiva)")
    hosp_for_season = st.selectbox("Hospital para decomposição", options=sel_hosp)
    series_sel = st.selectbox("Série", ["Valor","Producao","Custo_por_Producao"], index=0)
    df_season = dfm[dfm["Hospital"]==hosp_for_season].set_index("Data").sort_index()
    try:
        dec = seasonal_decompose(df_season[series_sel].asfreq("MS").interpolate(), model="additive", period=12)
        dfd = pd.DataFrame({
            "Observado": dec.observed,
            "Tendência": dec.trend,
            "Sazonal": dec.seasonal,
            "Resíduo": dec.resid
        }).reset_index().rename(columns={"index":"Data"})
        for comp in ["Observado","Tendência","Sazonal","Resíduo"]:
            st.altair_chart(alt.Chart(dfd).mark_line().encode(x="yearmonth(Data):T", y=f"{comp}:Q"), use_container_width=True)
    except Exception as e:
        st.info("Não foi possível decompor a série (dados insuficientes).")

    st.subheader("Detecção de outliers")
    serie_out = st.selectbox("Série para outlier", ["Var_Valor_pct","Var_Producao_pct","Var_Custo_por_Producao_pct"], index=0)
    df_out = dfm.copy()
    df_out["Outlier"] = iqr_outliers(df_out[serie_out])
    st.dataframe(df_out.loc[df_out["Outlier"], ["Hospital","Data",serie_out]].sort_values(["Hospital","Data"]), use_container_width=True)

    st.markdown("#### Alertas automáticos")
    df_alert = dfm[(dfm["Var_Valor_pct"].abs()>alert_threshold) | (dfm["Var_Producao_pct"].abs()>alert_threshold)].copy()
    st.dataframe(df_alert[["Hospital","Data","Var_Valor_pct","Var_Producao_pct"]].sort_values(["Hospital","Data"]), use_container_width=True)

with tab4:
    st.subheader("Ranking por Custo/Produção")
    bench = dfm.groupby("Hospital", as_index=False).agg(
        Custo_total=("Valor","sum"),
        Producao_total=("Producao","sum"),
        Custo_por_Producao_medio=("Custo_por_Producao","mean"),
        Desvio_padrao=("Custo_por_Producao","std"),
        CV=("Custo_por_Producao", lambda s: (s.std()/s.mean())*100 if s.mean() else np.nan)
    )
    bench["Ranking (menor melhor)"] = bench["Custo_por_Producao_medio"].rank(method="min")
    st.dataframe(bench.sort_values("Custo_por_Producao_medio"), use_container_width=True)

    st.markdown("#### Evolução do Custo/Produção")
    st.altair_chart(
        alt.Chart(dfm).mark_line().encode(
            x=alt.X("yearmonth(Data):T"),
            y=alt.Y("Custo_por_Producao:Q"),
            color="Hospital:N"
        ), use_container_width=True
    )

    st.markdown("#### Projeções simples (tendência linear)")
    horizon = st.slider("Meses à frente", 1, 12, 6)
    proj_metric = st.selectbox("Métrica a projetar", ["Valor","Producao","Custo_por_Producao"], index=2)
    proj_rows = []
    for h in sel_hosp:
        dfx = dfm[dfm["Hospital"]==h].sort_values("Data")
        if len(dfx) >= 3:
            X = np.arange(len(dfx)).reshape(-1,1)
            y = dfx[proj_metric].values.reshape(-1,1)
            lr = LinearRegression().fit(X,y)
            future_idx = np.arange(len(dfx), len(dfx)+horizon).reshape(-1,1)
            preds = lr.predict(future_idx).flatten()
            last_date = dfx["Data"].max()
            future_dates = pd.date_range(last_date + pd.offsets.MonthBegin(1), periods=horizon, freq="MS")
            proj_rows += [{"Hospital": h, "Data": d, proj_metric: p, "Tipo": "Projeção"} for d,p in zip(future_dates, preds)]
    df_proj = pd.concat([dfm[["Hospital","Data",proj_metric]].assign(Tipo="Observado"), pd.DataFrame(proj_rows)], ignore_index=True)
    st.altair_chart(
        alt.Chart(df_proj).mark_line().encode(
            x=alt.X("yearmonth(Data):T"),
            y=alt.Y(f"{proj_metric}:Q"),
            color="Hospital:N",
            strokeDash="Tipo:N"
        ), use_container_width=True
    )

with tab5:
    st.subheader("Exportações")
    colA, colB = st.columns(2)
    with colA:
        st.markdown("**Exportar dados filtrados (Excel)**")
        download_button_df(dfm, "custos_x_producao_filtrado.xlsx")
        st.markdown("**Exportar ranking (Excel)**")
        download_button_df(bench.sort_values("Custo_por_Producao_medio"), "benchmarking.xlsx")
    with colB:
        st.markdown("**Exportar dispersões (CSV)**")
        download_button_df(dfm[["Hospital","Data","Valor","Producao","Var_Valor_pct","Var_Producao_pct"]], "dispersoes.xlsx")

    st.markdown("---")
    st.subheader("Relatório executivo (PDF)")
    st.markdown("Gera um sumário com KPIs, correlações e ranking. (Este PDF é textual; para gráficos, recomendamos capturas pelo próprio navegador.)")
    if st.button("Gerar PDF"):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas
        buff = BytesIO()
        c = canvas.Canvas(buff, pagesize=A4)
        width, height = A4
        pos = {"y": height - 2*cm}
        def writeln(txt, size=11):
            c.setFont("Helvetica", size)
            for line in txt.splitlines():
                c.drawString(2*cm, y, line)
                y -= 14
        writeln("FHEMIG — Relatório Executivo: Custos × Produção", 14)
        writeln(f"Período: {date_range[0].strftime('%m/%Y')} – {date_range[1].strftime('%m/%Y')}")
        writeln(f"Hospitais: {', '.join(sel_hosp)}")
        writeln("")
        writeln(f"Custo total (R$): {dfm['Valor'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
        writeln(f"Total {metric_sel}: {dfm['Producao'].sum():,.0f}".replace(",", "X").replace(".", ",").replace("X","."))
        r_lvl, p_lvl = corr_stats(dfm["Valor"], dfm["Producao"])
        r_var, p_var = corr_stats(dfm["Var_Valor_pct"], dfm["Var_Producao_pct"])
        writeln("")
        writeln(f"Correlação (níveis): {r_lvl:.3f} | p-valor {p_lvl:.4f}" if pd.notna(r_lvl) else "Correlação (níveis): N/A")
        writeln(f"Correlação (variações): {r_var:.3f} | p-valor {p_var:.4f}" if pd.notna(r_var) else "Correlação (variações): N/A")
        writeln("")
        writeln("Benchmarking (menor Custo/Produção é melhor):")
        top = bench.sort_values("Custo_por_Producao_medio").head(10)
        for _, r in top.iterrows():
            writeln(f"- {r['Hospital']}: média {r['Custo_por_Producao_medio']:.2f} | CV {r['CV']:.1f}%")
        c.showPage()
        c.save()
        buff.seek(0)
        st.download_button("Baixar relatório PDF", data=buff, file_name="relatorio_executivo_fhemig.pdf", mime="application/pdf")

with st.expander("ℹ️ Guia rápido de interpretação"):
    st.markdown(
"""
**Correlação (r):** mede a associação linear entre duas variáveis (entre -1 e 1).  
**p-valor:** probabilidade da correlação observada ocorrer ao acaso (quanto menor, mais significativo).  
**R²:** proporção da variação explicada por um modelo de regressão linear (0 a 1).  
**Custo/Produção:** indicador sintético de custo-efetividade (menor costuma ser melhor).  
**CV (coef. variação):** dispersão relativa (desvio padrão / média).  
**Outliers:** pontos que se desviam fortemente do padrão.  
"""
        "**Heatmap:** padrões sazonais por mês/ano."
    )
