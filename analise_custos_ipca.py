# fhemig_app.py
import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
from io import BytesIO

st.set_page_config(page_title="FHEMIG | Custos × Produção", layout="wide")

# ---------------------------
# Arquivos (primeira aba)
# ---------------------------
CUSTOS_XLS = "dados_custos.xlsx"
PROD_XLS   = "dados_producao.xlsx"

try:
    df_costs_raw = pd.ExcelFile(CUSTOS_XLS).parse(0)
    df_prod_raw  = pd.ExcelFile(PROD_XLS).parse(0)
except Exception as e:
    st.error("Não foi possível abrir os arquivos no diretório. "
             "Confirme se **dados_custos.xlsx** e **dados_producao.xlsx** estão na mesma pasta do app. "
             f"Detalhe: {e}")
    st.stop()

# ---------------------------
# Helpers
# ---------------------------
PT_MONTHS = {
    "janeiro":1, "jan":1, "fevereiro":2, "fev":2, "março":3, "marco":3, "mar":3,
    "abril":4, "abr":4, "maio":5, "mai":5, "junho":6, "jun":6, "julho":7, "jul":7,
    "agosto":8, "ago":8, "setembro":9, "set":9, "outubro":10, "out":10,
    "novembro":11, "nov":11, "dezembro":12, "dez":12
}

def to_month(m):
    if pd.isna(m): return np.nan
    s = str(m).strip().lower()
    try:
        v = int(float(s))
        if 1 <= v <= 12: return v
    except: pass
    return PT_MONTHS.get(s, np.nan)

def parse_br_number(x):
    """ '4.743'->4743 ; '-919,21'->-919.21 ; mantém floats """
    if pd.isna(x): return np.nan
    if isinstance(x,(int,float,np.number)): return float(x)
    s = str(x).strip().replace(" ", "")
    if "," in s: s = s.replace(".", "").replace(",", ".")
    else: s = s.replace(".", "")
    try: return float(s)
    except: return np.nan

def safediv(a, b):
    with np.errstate(divide='ignore', invalid='ignore'):
        out = np.true_divide(a, b)
        out[~np.isfinite(out)] = np.nan
    return out

# ---------------------------
# IPCA via python-bcb (SGS 433)
# ---------------------------
@st.cache_data(show_spinner=False)
def fetch_ipca_bcb(dt_start, dt_end):
    """Retorna DataFrame ['Data','ipca_var_pct','ipca_indice'] ou (None,msg) em caso de erro."""
    try:
        from bcb import sgs  # pip install python-bcb
    except Exception:
        return None, "Pacote 'python-bcb' não encontrado. Instale com: pip install python-bcb"
    try:
        ipca = sgs.get(("ipca_var_pct", 433),
                       start=pd.to_datetime(dt_start).strftime("%Y-%m-%d"),
                       end=pd.to_datetime(dt_end).strftime("%Y-%m-%d"))
        ipca = ipca.reset_index().rename(columns={"Date":"Data"})
        ipca["Data"] = pd.to_datetime(ipca["Data"]).dt.to_period("M").dt.to_timestamp()
        ipca = ipca.sort_values("Data")
        ipca["ipca_indice"] = (1 + ipca["ipca_var_pct"]/100.0).cumprod()
        return ipca[["Data","ipca_var_pct","ipca_indice"]], None
    except Exception as e:
        return None, f"Falha ao consultar IPCA via python-bcb/SGS: {e}"

# ---------------------------
# Adaptação de colunas
# ---------------------------
# Custos
req_costs = ["Hospital","Competência - Ano","Competência - Mês","Grupo do item","Item de Custo","Valor"]
if not set(req_costs).issubset(df_costs_raw.columns):
    st.error("Planilha de **custos** deve conter: " + ", ".join(req_costs)); st.stop()

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
df_costs["Data"]  = pd.to_datetime(dict(year=df_costs["Ano"], month=df_costs["Mes"], day=1), errors="coerce")
df_costs = df_costs.dropna(subset=["Data"])

# Produção
req_prod_min = ["Estabelecimento","data - Ano","data - Mês"]
if not set(req_prod_min).issubset(df_prod_raw.columns):
    st.error("Planilha de **produção** deve conter: Estabelecimento, data - Ano, data - Mês + métricas."); st.stop()

df_prod = df_prod_raw.rename(columns={"Estabelecimento":"Hospital","data - Ano":"Ano","data - Mês":"Mes"}).copy()
df_prod["Ano"] = pd.to_numeric(df_prod["Ano"], errors="coerce")
df_prod["Mes"] = df_prod["Mes"].apply(to_month)
for c in df_prod.columns:
    if c not in ["Hospital","Ano","Mes"]:
        df_prod[c] = df_prod[c].apply(parse_br_number)
df_prod = df_prod.dropna(subset=["Hospital","Ano","Mes"])
df_prod["Data"] = pd.to_datetime(dict(year=df_prod["Ano"], month=df_prod["Mes"], day=1), errors="coerce")
df_prod = df_prod.dropna(subset=["Data"])

metric_candidates = [c for c in df_prod.select_dtypes(include=["number"]).columns if c not in ["Ano","Mes"]]
if not metric_candidates:
    st.error("Nenhuma métrica numérica de produção encontrada."); st.stop()

# ---------------------------
# Filtros
# ---------------------------
st.sidebar.header("🔎 Filtros")
hosp_all = sorted(set(df_costs["Hospital"]) | set(df_prod["Hospital"]))
sel_hosp = st.sidebar.multiselect("Hospitais", hosp_all, default=hosp_all)

# se não selecionar nenhum hospital:
if len(sel_hosp) == 0:
    st.warning("⚠️ Selecione ao menos um hospital para exibir os dados.")
    st.stop()

grupos = ["(Todos)"] + sorted(df_costs["Grupo"].dropna().unique().tolist())
sel_grupo = st.sidebar.selectbox("Grupo de despesa", grupos, index=0)
metric_sel = st.sidebar.selectbox("Indicador de produção", metric_candidates, index=0)
ajuste_preco = st.sidebar.radio("Série de preços", ["Nominal", "Deflacionado (IPCA/BCB)"], horizontal=True, index=0)

costs_f = df_costs[df_costs["Hospital"].isin(sel_hosp)].copy()
if sel_grupo != "(Todos)": costs_f = costs_f[costs_f["Grupo"] == sel_grupo]
prod_f  = df_prod[df_prod["Hospital"].isin(sel_hosp)].copy()

min_date = max(costs_f["Data"].min(), prod_f["Data"].min())
max_date = min(costs_f["Data"].max(), prod_f["Data"].max())
date_range = st.sidebar.slider("Período",
    min_value=min_date.to_pydatetime(), max_value=max_date.to_pydatetime(),
    value=(min_date.to_pydatetime(), max_date.to_pydatetime()), format="MM/YYYY")

costs_f = costs_f[(costs_f["Data"] >= pd.to_datetime(date_range[0])) & (costs_f["Data"] <= pd.to_datetime(date_range[1]))]
prod_f  = prod_f[(prod_f["Data"]  >= pd.to_datetime(date_range[0])) & (prod_f["Data"]  <= pd.to_datetime(date_range[1]))]

# ---------------------------
# Merge (Hospital/Ano/Mes)
# ---------------------------
costs_m = costs_f.groupby(["Hospital","Ano","Mes","Data"], as_index=False)["Valor"].sum()
prod_m  = (prod_f.groupby(["Hospital","Ano","Mes","Data"], as_index=False)[metric_sel]
                .sum().rename(columns={metric_sel:"Producao"}))
df = pd.merge(costs_m, prod_m, on=["Hospital","Ano","Mes","Data"], how="inner").sort_values(["Hospital","Data"])
if df.empty:
    st.warning("Sem interseção entre custos e produção após filtros/período."); st.stop()

# agregado para gráficos
df_cols = df.groupby("Data", as_index=False).agg(Valor=("Valor","sum"), Producao=("Producao","sum")).sort_values("Data")

# ---------------------------
# IPCA (deflação opcional)
# ---------------------------
ipca_df = None; ipca_msg = None
if ajuste_preco == "Deflacionado (IPCA/BCB)":
    ipca_df, ipca_msg = fetch_ipca_bcb(df_cols["Data"].min(), df_cols["Data"].max())
    if ipca_df is None:
        st.warning(f"Não foi possível aplicar IPCA agora. Motivo: {ipca_msg}. Exibindo valores nominais.")
        ajuste_preco = "Nominal"

if ajuste_preco == "Deflacionado (IPCA/BCB)" and ipca_df is not None:
    df_cols_plot = pd.merge(df_cols, ipca_df[["Data","ipca_indice"]], on="Data", how="left").sort_values("Data")
    ind_last = df_cols_plot["ipca_indice"].dropna().iloc[-1]
    df_cols_plot["ind_rebased"] = df_cols_plot["ipca_indice"] / ind_last
    df_cols_plot["Valor_ajustado"] = safediv(df_cols_plot["Valor"], df_cols_plot["ind_rebased"])
    legenda_custo = "Custo deflacionado (R$ de mês mais recente)"
    st.caption("**Nota (IPCA)**: custos deflacionados para o mês mais recente do período (SGS/BCB série 433).")
else:
    df_cols_plot = df_cols.copy()
    df_cols_plot["Valor_ajustado"] = df_cols_plot["Valor"]
    legenda_custo = "Custo nominal (R$)"

# IPCA acumulado (box)
ipca_acum_txt = "—"
if (ajuste_preco == "Deflacionado (IPCA/BCB)") and (ipca_df is not None) and (not ipca_df.empty):
    dt_min, dt_max = df_cols_plot["Data"].min(), df_cols_plot["Data"].max()
    ip = ipca_df[(ipca_df["Data"] >= dt_min) & (ipca_df["Data"] <= dt_max)].dropna(subset=["ipca_indice"]).sort_values("Data")
    if not ip.empty:
        ipca_acum = (ip["ipca_indice"].iloc[-1] / ip["ipca_indice"].iloc[0] - 1) * 100
        ipca_acum_txt = f"{ipca_acum:.1f}%"

# ---------------------------
# Header
# ---------------------------
st.title("🏥 FHEMIG — Custos × Produção")
c1, c2, c3 = st.columns(3)
c1.metric("Hospitais", f"{len(sel_hosp)}")
c2.metric("Grupo", sel_grupo)
c3.metric("IPCA acumulado", ipca_acum_txt)


# ---------------------------
# Gráfico 1 – Barras (Custo) + Linha (Produção), 2 eixos Y
# ---------------------------
st.subheader("Custo × Produção (sem rótulos fixos)")

base_x = alt.X("yearmonth(Data):T", title="Competência")
bar_custo = alt.Chart(df_cols_plot).mark_bar(opacity=0.6).encode(
    x=base_x,
    y=alt.Y("Valor_ajustado:Q", axis=alt.Axis(title=legenda_custo)),
    tooltip=[alt.Tooltip("yearmonth(Data):T", title="Competência"),
             alt.Tooltip("Valor_ajustado:Q", title=legenda_custo, format=",.0f")]
)
line_prod = (alt.Chart(df_cols_plot).mark_line(size=3)
             .encode(x=base_x,
                     y=alt.Y("Producao:Q", axis=alt.Axis(title=f"Produção ({metric_sel})", orient="right")),
                     color=alt.value("#e61919"),
                     tooltip=[alt.Tooltip("yearmonth(Data):T", title="Competência"),
                              alt.Tooltip("Producao:Q", title=f"Produção ({metric_sel})", format=",.0f")])
             + alt.Chart(df_cols_plot).mark_point(size=50, filled=True, color="#e61919").encode(x=base_x, y="Producao:Q"))

st.altair_chart(alt.layer(bar_custo, line_prod).resolve_scale(y="independent").properties(height=380).interactive(),
                use_container_width=True)

# ---------------------------
# Gráfico 2 – Eficiência
# ---------------------------
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

# ---------------------------
# Tabela executiva por hospital
# ---------------------------
st.subheader("Resumo por hospital — variação no período")

df_h = df[["Hospital","Data","Valor","Producao"]].sort_values(["Hospital","Data"])
if (ajuste_preco == "Deflacionado (IPCA/BCB)") and (ipca_df is not None):
    aux = pd.merge(df_h, ipca_df[["Data","ipca_indice"]], on="Data", how="left").sort_values(["Hospital","Data"])
    def last_nonnull(s):
        s = s.dropna()
        return s.iloc[-1] if len(s) else np.nan
    ind_last_by_h = aux.groupby("Hospital")["ipca_indice"].transform(last_nonnull)
    aux["ind_rebased"] = safediv(aux["ipca_indice"], ind_last_by_h)
    aux["Valor_real"]  = safediv(aux["Valor"], aux["ind_rebased"])
else:
    aux = df_h.copy()
    aux["Valor_real"] = np.nan

def first_valid(s): s=s.dropna(); return s.iloc[0] if len(s) else np.nan
def last_valid(s):  s=s.dropna(); return s.iloc[-1] if len(s) else np.nan

res = (aux.groupby("Hospital")
          .agg(
              Custo_nominal_ini=("Valor", first_valid),
              Custo_nominal_fim=("Valor", last_valid),
              Producao_ini=("Producao", first_valid),
              Producao_fim=("Producao", last_valid),
              Custo_real_ini=("Valor_real", first_valid),
              Custo_real_fim=("Valor_real", last_valid),
          ).reset_index())

res["Variação nominal (%)"] = safediv(res["Custo_nominal_fim"] - res["Custo_nominal_ini"], res["Custo_nominal_ini"])*100
if (ajuste_preco == "Deflacionado (IPCA/BCB)") and (ipca_df is not None):
    res["Variação real (%)"] = safediv(res["Custo_real_fim"] - res["Custo_real_ini"], res["Custo_real_ini"])*100
else:
    res["Variação real (%)"] = np.nan
res["Variação da produção (%)"] = safediv(res["Producao_fim"] - res["Producao_ini"], res["Producao_ini"])*100

# formatações amigáveis para exibição
def fmt_money(v, nd=2): 
    return "-" if pd.isna(v) else f"{v:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X",".")
def fmt_pct(v): 
    return "-" if pd.isna(v) else f"{v:.1f}%"

res_show = res.rename(columns={
    "Hospital":"Hospital",
    "Custo_nominal_ini":"Custo nominal (início)",
    "Custo_nominal_fim":"Custo nominal (fim)",
    "Custo_real_ini":"Custo real (início)",
    "Custo_real_fim":"Custo real (fim)",
    "Producao_ini":f"Produção (início) — {metric_sel}",
    "Producao_fim":f"Produção (fim) — {metric_sel}",
})

for c in ["Custo nominal (início)","Custo nominal (fim)","Custo real (início)","Custo real (fim)",
          f"Produção (início) — {metric_sel}", f"Produção (fim) — {metric_sel}"]:
    res_show[c] = res_show[c].apply(lambda v: fmt_money(v, 2 if "Custo" in c else 0))
for c in ["Variação nominal (%)","Variação real (%)","Variação da produção (%)"]:
    res_show[c] = res_show[c].apply(fmt_pct)

cols_order = [
    "Hospital",
    "Custo nominal (início)","Custo nominal (fim)","Variação nominal (%)",
    "Custo real (início)","Custo real (fim)","Variação real (%)",
    f"Produção (início) — {metric_sel}", f"Produção (fim) — {metric_sel}","Variação da produção (%)"
]
st.dataframe(res_show[cols_order], use_container_width=True)

# ---------------------------
# Exportações (Excel e PDF)
# ---------------------------
from io import BytesIO

def to_excel_bytes(dfs_dict, number_formats=None):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        for sheet, df_ in dfs_dict.items():
            df_.to_excel(writer, sheet_name=sheet, index=False)
            wb  = writer.book
            ws  = writer.sheets[sheet]
            for i, col in enumerate(df_.columns):
                width = max(12, min(50, int(df_[col].astype(str).map(len).max() if len(df_) else 12)))
                ws.set_column(i, i, width + 2)
            if number_formats and sheet in number_formats:
                for col, fmt in number_formats[sheet].items():
                    if col in df_.columns:
                        col_idx = df_.columns.get_loc(col)
                        numfmt = wb.add_format({"num_format": fmt})
                        ws.set_column(col_idx, col_idx, None, numfmt)
    buf.seek(0); return buf

def to_pdf_bytes(resumo_df, titulo, subtitulo, nota_ipca=None, landscape=True):
    """
    Gera PDF com cabeçalho + tabela larga, ajustando colunas à página.
    Requer: reportlab  (pip install reportlab)
    """
    try:
        from reportlab.lib.pagesizes import A4, landscape as rl_landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, LongTable
    except Exception:
        return None, "Pacote 'reportlab' não encontrado. Instale com: pip install reportlab"

    # --- tamanhos de página e margens ---
    pagesize = rl_landscape(A4) if landscape else A4
    left, right, top, bottom = 28, 28, 30, 28  # mm aprox (em pontos)
    # reportlab trabalha em pontos; os valores acima já estão em pontos aprox para simplificar
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=pagesize,
        leftMargin=left, rightMargin=right, topMargin=top, bottomMargin=bottom
    )

    styles = getSampleStyleSheet()
    h_style = styles["Title"]
    sub_style = styles["Normal"]
    sub_style.fontSize = 10
    note_style = styles["Normal"]
    note_style.fontSize = 8
    note_style.textColor = colors.HexColor("#555")

    # --- prepara headers curtos para caber melhor no PDF ---
    header_map = {
        "Hospital": "Hospital",
        "Custo nominal (início)": "Custo nominal\n(início)",
        "Custo nominal (fim)": "Custo nominal\n(fim)",
        "Variação nominal (%)": "Var. nominal\n(%)",
        "Custo real (início)": "Custo real\n(início)",
        "Custo real (fim)": "Custo real\n(fim)",
        "Variação real (%)": "Var. real\n(%)",
        # produção vem com o nome do indicador, pode ficar enorme → quebra:
        # Ex.: "Produção (início) — Leito dia"
        **{c: c.replace(" — ", "\n— ") for c in resumo_df.columns if "Produção (" in c},
        "Variação da produção (%)": "Var. produção\n(%)",
    }

    show_df = resumo_df.copy()
    show_df.columns = [header_map.get(c, c) for c in show_df.columns]

    # --- estimativa de largura por coluna (com min/max) ---
    # conta caracteres de cabeçalho e das primeiras N linhas
    N = min(50, len(show_df))
    col_scores = []
    for i, col in enumerate(show_df.columns):
        header_len = max(len(line) for line in col.split("\n"))
        body_len = int(show_df[col].astype(str).str.len().head(N).max() or 0)
        score = max(header_len, body_len)
        col_scores.append(score if score > 0 else 1)

    total_score = sum(col_scores)
    avail_width = pagesize[0] - left - right  # largura útil
    # limites em pontos (aprox.): mínimo 60, máximo 150
    min_w, max_w = 60, 150
    raw_widths = [max(min_w, min(max_w, avail_width * (s / total_score))) for s in col_scores]

    # se sobrou/lack de poucos px por arredondamento, normaliza:
    scale = avail_width / sum(raw_widths)
    col_widths = [w * scale for w in raw_widths]

    # --- transforma cabeçalho em Paragraph (para permitir quebra) ---
    head_style = ParagraphStyle(
        "head", parent=styles["Normal"], fontSize=8.5, alignment=1, leading=10, textColor=colors.HexColor("#222"),
    )
    data = [[Paragraph(h, head_style) for h in show_df.columns]]

    # --- linhas da tabela (já vêm formatadas no app) ---
    data += show_df.values.tolist()

    # usa LongTable para quebrar entre páginas e repetir cabeçalho
    tbl = LongTable(data, colWidths=col_widths, repeatRows=1)

    # detecta colunas numéricas por padrão (direita). Como a gente já formatou como string,
    # tratamos por heurística: se a coluna contém números/%, alinha à direita
    num_cols = [j for j, col in enumerate(show_df.columns)
                if ("%" in col.lower()) or ("custo" in col.lower()) or ("produção" in col.lower())]

    style_cmds = [
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f2f2f2")),
        ("LINEBELOW", (0,0), (-1,0), 0.6, colors.HexColor("#d0d0d0")),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#e0e0e0")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,0), 8.5),
        ("FONTSIZE", (0,1), (-1,-1), 8),
        ("ALIGN", (0,1), (-1,-1), "CENTER"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#fbfbfb")]),
        ("LEFTPADDING",(0,0), (-1,-1), 4),
        ("RIGHTPADDING",(0,0), (-1,-1), 4),
        ("TOPPADDING",(0,0), (-1,-1), 2),
        ("BOTTOMPADDING",(0,0), (-1,-1), 2),
    ]
    for j in num_cols:
        style_cmds.append(("ALIGN", (j,1), (j,-1), "RIGHT"))

    tbl.setStyle(TableStyle(style_cmds))

    elems = [
        Paragraph(f"<b>{titulo}</b>", h_style),
        Paragraph(subtitulo, sub_style),
    ]
    if nota_ipca:
        elems.append(Paragraph(nota_ipca, note_style))
    elems.append(Spacer(1, 8))
    elems.append(tbl)

    doc.build(elems)
    buf.seek(0)
    return buf, None


# datasets p/ exportação
serie_export = df_cols_plot[["Data","Valor_ajustado","Producao"]].copy().sort_values("Data")
serie_export["Competência"] = serie_export["Data"].dt.strftime("%Y-%m")
serie_export = serie_export[["Competência","Valor_ajustado","Producao"]].rename(
    columns={"Valor_ajustado":"Custo (R$)", "Producao":f"Produção ({metric_sel})"})

efic_export = df_eff[["Data","Custo_por_Unid"]].copy().sort_values("Data")
efic_export["Competência"] = efic_export["Data"].dt.strftime("%Y-%m")
efic_export = efic_export[["Competência","Custo_por_Unid"]].rename(
    columns={"Custo_por_Unid":f"Custo por {metric_sel} (R$)"})

xlsx_buf = to_excel_bytes(
    {"Série": serie_export, "Eficiência": efic_export, "Resumo por hospital": res_show[cols_order]},
    number_formats={
        "Série": {"Custo (R$)":"#,##0", f"Produção ({metric_sel})":"#,##0"},
        "Eficiência": {f"Custo por {metric_sel} (R$)":"#,##0.00"},
    }
)

col_b1, col_b2 = st.columns(2)
col_b1.download_button("⬇️ Baixar Excel (xlsx)", data=xlsx_buf,
                       file_name="fhemig_custos_producao.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

nota_ipca = None
if ajuste_preco.startswith("Deflacionado") and ipca_df is not None:
    nota_ipca = ("<font size=9>Valores de custo deflacionados pelo IPCA (SGS 433), "
                 "re-escalados para o mês mais recente do período. "
                 "Variações calculadas entre o primeiro e o último mês disponíveis por hospital.</font>")

pdf_buf, pdf_err = to_pdf_bytes(
    res_show[cols_order],  # << já com cabeçalhos amigáveis
    titulo="FHEMIG — Resumo Executivo: Custos × Produção",
    subtitulo=f"Período: {date_range[0].strftime('%m/%Y')} – {date_range[1].strftime('%m/%Y')} | "
              f"Grupo: {sel_grupo} | Indicador: {metric_sel}",
    nota_ipca=nota_ipca,
    landscape=True  # paisagem para caber mais colunas
)

if pdf_buf is not None:
    col_b2.download_button("⬇️ Baixar PDF (resumo executivo)",
                           data=pdf_buf, file_name="fhemig_resumo_executivo.pdf", mime="application/pdf")
else:
    col_b2.info("Para exportar PDF, instale:  `pip install reportlab`")

# Rodapé
st.markdown("---")
st.markdown("**Metodologia**: valores deflacionados pelo IPCA (SGS/BCB 433) mês a mês, rebase no mês final do período. "
            "Eficiência = custo / produção. Gráficos sem rótulos fixos para leitura limpa; números completos nos tooltips.")
