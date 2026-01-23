from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass
class Slide2:
    contexto: list[str]
    conceito: list[str]
    infraestrutura: list[str]
    presenca_digital: list[str]
    scores: list[str]


@dataclass
class Slide3:
    pontos_positivos: list[str]
    pontos_atencao: list[str]


@dataclass
class Slide4:
    problema_critico: str
    impacto: str
    indexacao: str
    deficiencias: list[str]
    risco_competitivo: list[str]


@dataclass
class Slide5:
    navegacao: str
    conversao: list[str]
    jornada: str
    lacunas: list[str]


@dataclass
class Slide6:
    positivo: list[str]
    requer_validacao: list[str]


@dataclass
class Slide7:
    comunicacao: list[str]
    dados_concretos: list[str]
    lacunas: list[str]


@dataclass
class Slide8:
    pontos_fortes: list[str]


@dataclass
class Slide9:
    performance: list[str]
    seo: list[str]
    ux: list[str]
    conversao: list[str]


@dataclass
class Slide10:
    acoes: list[str]


@dataclass
class Slide11:
    situacao_atual: list[str]
    desafios: list[str]
    necessidade: list[str]


@dataclass
class ReportSlides:
    slide2: Slide2
    slide3: Slide3
    slide4: Slide4
    slide5: Slide5
    slide6: Slide6
    slide7: Slide7
    slide8: Slide8
    slide9: Slide9
    slide10: Slide10
    slide11: Slide11


def _ensure(items: list[str], fallback: str) -> list[str]:
    return items if items else [fallback]


def _primary_page(result: dict) -> dict:
    if result.get("page"):
        return result["page"]
    pages = result.get("pages") or []
    return pages[0] if pages else {}


def _brand_name(page: dict, context: dict, url: str) -> str:
    if context.get("brand_name"):
        return str(context["brand_name"]).strip()
    title = page.get("title") or ""
    if title:
        for sep in [" | ", " - ", " \u2014 "]:
            if sep in title:
                return title.split(sep, 1)[0].strip()
        return title.strip()
    parsed = urlparse(url)
    domain = parsed.netloc or url
    return domain.replace("www.", "").split(".")[0].strip() or "Projeto"


def _paths_summary(pages: list[dict], limit: int = 5) -> str:
    if not pages:
        return "Requer validacao"
    paths = []
    for page in pages:
        path = urlparse(page.get("url", "")).path or "/"
        if path == "":
            path = "/"
        paths.append(path)
    unique_paths = sorted(set(paths))
    shown = ", ".join(unique_paths[:limit])
    return f"({len(unique_paths)} paginas analisadas) {shown}"


def _critical_problem(signals: dict) -> tuple[str, str]:
    if signals.get("duplicate_home"):
        return (
            "Conteudo duplicado entre / e /home.",
            "Risco de canibalizacao de palavras-chave e perda de relevancia.",
        )
    if signals.get("indexable") is False:
        return (
            "Pagina com indicacao de noindex.",
            "Pode impedir indexacao e derrubar visibilidade organica.",
        )
    if not signals.get("has_canonical"):
        return (
            "Canonical ausente na pagina principal.",
            "Risco de duplicacao tecnica e enfraquecimento de SEO.",
        )
    if not signals.get("meta_description"):
        return (
            "Meta description ausente ou incompleta.",
            "Reduz CTR organico e clareza do snippet.",
        )
    return (
        "Sem evidencias de problema critico confirmado.",
        "Requer validacao com auditoria completa de indexacao.",
    )


def _journey_line(has_cta: bool, content_depth: bool, nav_items: list[str]) -> str:
    optimized = []
    deficient = []
    if nav_items:
        optimized.append("navegacao estruturada")
    if content_depth:
        optimized.append("educacao inicial")
    if has_cta:
        optimized.append("contato/lead")
    if not has_cta:
        deficient.append("conversao e captura de lead")
    if not content_depth:
        deficient.append("educacao e comparacao")
    optimized_text = ", ".join(optimized) if optimized else "descoberta basica"
    deficient_text = ", ".join(deficient) if deficient else "sem deficiencias evidentes"
    return f"Otimizada para: {optimized_text} | Deficiente para: {deficient_text}"


def _build_opportunities(signals: dict) -> list[str]:
    actions: list[str] = []
    duplicate_home = signals.get("duplicate_home")
    is_real_estate = signals.get("is_real_estate")
    seo_gaps = signals.get("seo_gaps", [])
    conversion_gaps = signals.get("conversion_gaps", [])

    if duplicate_home:
        actions.append("Aplicar canonical e 301 para eliminar duplicacao entre / e /home.")
    else:
        actions.append("Revisar canonical e redirecionamentos 301 para evitar duplicacao.")

    if is_real_estate:
        actions.append("Implementar schema RealEstateListing e LocalBusiness.")
    else:
        actions.append("Implementar schema LocalBusiness/Organization conforme o segmento.")

    actions.append("Revisar titles e meta descriptions com foco em CTR e palavras-chave.")
    actions.append("Criar FAQ estrategico para capturar buscas de cauda longa.")
    actions.append("Adicionar prova social (depoimentos, cases, numeros verificaveis).")
    actions.append("Otimizar galeria com imagens WebP/AVIF e incluir tour 360 quando aplicavel.")
    actions.append("Aplicar CDN, cache e compressao para reduzir tempo de carregamento.")
    actions.append("Criar materiais ricos (guia, checklist, ebook) para captura de leads.")
    actions.append("Revisar CTAs e formularios para reduzir friccao de conversao.")
    actions.append("Expandir conteudo com beneficios, diferenciais e etapas do processo.")

    if "chatbot" in conversion_gaps:
        actions.append("Implantar chatbot de IA para qualificacao de leads.")
    if "pos_venda" in conversion_gaps:
        actions.append("Criar plataforma de relacionamento pos-venda com clientes.")
    if "sitemap" in seo_gaps:
        actions.append("Publicar sitemap/robots e monitorar indexacao no Google Search Console.")

    return actions[:15]


def build_report_slides(
    result: dict,
    context: Optional[dict] = None,
) -> ReportSlides:
    context = context or result.get("context") or {}

    page = _primary_page(result)
    pages = result.get("pages") or []
    diagnostics = result.get("diagnostics") or {}

    url = result.get("input", {}).get("url") or page.get("url") or ""
    brand = _brand_name(page, context, url)

    ssl = str(url).startswith("https://")
    has_viewport = bool(page.get("has_viewport"))
    page_size_kb = page.get("page_size_kb")
    images_total = page.get("images_total", 0)
    lazy_loading = bool(page.get("lazy_loading_present"))
    render_blocking = page.get("render_blocking_scripts", 0)
    cdn_hints = bool(page.get("cdn_hints"))
    image_formats = page.get("image_formats") or {}

    has_canonical = bool(page.get("has_canonical"))
    has_schema = bool(page.get("has_schema"))
    has_og = bool(page.get("has_og"))
    meta_description = page.get("meta_description")
    indexable = page.get("indexable")
    h1_count = page.get("h1_count", 0)

    nav_items = page.get("nav_items") or []
    cta_texts = page.get("cta_texts") or []
    has_form = bool(page.get("has_form"))
    has_whatsapp = bool(page.get("has_whatsapp"))
    has_faq = bool(page.get("has_faq"))
    has_gallery = bool(page.get("has_gallery"))
    has_testimonials = bool(page.get("has_testimonials"))
    has_pricing = bool(page.get("has_pricing"))
    has_numbers = bool(page.get("has_numbers"))
    number_samples = page.get("number_samples") or []
    word_count = page.get("word_count", 0)
    section_count = page.get("section_count", 0)
    images_missing_alt = page.get("images_missing_alt", 0)
    h1_text = page.get("h1_text")
    internal_links_count = page.get("internal_links_count")

    segment_text = str(context.get("segment", "")).lower()
    is_real_estate = bool(page.get("is_real_estate")) or any(
        key in segment_text for key in ["imobili", "lote", "condominio", "empreendimento"]
    )

    duplicate_home = bool(diagnostics.get("duplicate_home"))
    if not duplicate_home and pages:
        root_page = next((p for p in pages if (urlparse(p.get("url", "")).path or "/").rstrip("/") in ["", "/"]), None)
        home_page = next((p for p in pages if (urlparse(p.get("url", "")).path or "").rstrip("/") == "home"), None)
        if root_page and home_page:
            title_match = (root_page.get("title") or "") == (home_page.get("title") or "")
            root_text = " ".join(f"{root_page.get('title', '')} {root_page.get('text_snippet', '')}".lower().split())
            home_text = " ".join(f"{home_page.get('title', '')} {home_page.get('text_snippet', '')}".lower().split())
            word_gap = abs((root_page.get("word_count") or 0) - (home_page.get("word_count") or 0))
            if title_match and (root_text == home_text or word_gap <= 20):
                duplicate_home = True

    signals = {
        "duplicate_home": duplicate_home,
        "indexable": indexable,
        "has_canonical": has_canonical,
        "meta_description": meta_description,
        "has_schema": has_schema,
        "has_og": has_og,
        "is_real_estate": is_real_estate,
    }

    contexto = []
    if context.get("segment"):
        contexto.append(f"Segmento: {context['segment']}")
    else:
        contexto.append("Segmento: Requer validacao")
    if context.get("city"):
        contexto.append(f"\U0001F4CD Cidade/Regiao: {context['city']}")
    if context.get("product"):
        contexto.append(f"Produto/Servico: {context['product']}")
    if context.get("differentiators"):
        contexto.append(f"Diferenciais: {', '.join(context['differentiators'])}")

    conceito = []
    if h1_text:
        conceito.append(f"Proposta aparente: \"{h1_text}\"")
    elif page.get("title"):
        conceito.append(f"Proposta aparente: \"{page.get('title')}\"")
    else:
        conceito.append("Proposta aparente: Requer validacao")
    if is_real_estate:
        conceito.append("Segmento identificado como mercado imobiliario/loteamentos.")

    infraestrutura = []
    infraestrutura.append("\U0001F512 HTTPS ativo" if ssl else "\U0001F512 HTTPS nao identificado")
    infraestrutura.append("Responsivo (meta viewport presente)." if has_viewport else "Responsividade: Requer validacao")
    if page_size_kb is not None:
        infraestrutura.append(f"Tamanho HTML ~{page_size_kb} KB.")
    else:
        infraestrutura.append("Tamanho de pagina: Requer validacao")

    presenca = []
    if context.get("social"):
        presenca.append("Canais sociais: " + ", ".join(context["social"]))
    elif has_og:
        presenca.append("Open Graph detectado (compartilhamento social).")
    else:
        presenca.append("Presenca social: Requer validacao")

    pos_perf = []
    if ssl:
        pos_perf.append("\u2705 HTTPS ativo (seguranca).")
    if has_viewport:
        pos_perf.append("\u2705 Meta viewport presente (responsivo).")
    if render_blocking == 0:
        pos_perf.append("\u2705 Sem scripts bloqueando renderizacao no head.")
    if lazy_loading:
        pos_perf.append("\u2705 Lazy-loading detectado em imagens.")
    if image_formats.get("webp") or image_formats.get("avif"):
        pos_perf.append("\u2705 Imagens em formatos modernos (WebP/AVIF).")
    if cdn_hints:
        pos_perf.append("\u2705 CDN/ativos externos otimizados detectados.")

    attention_perf = []
    if images_total >= 12:
        attention_perf.append(f"\u26a0 Muitas imagens ({images_total}); risco de peso alto.")
    if images_total >= 6 and not lazy_loading:
        attention_perf.append("\u26a0 Imagens sem lazy-loading visivel.")
    if render_blocking > 0:
        attention_perf.append(f"\u26a0 Scripts bloqueando renderizacao ({render_blocking}).")
    if page_size_kb is not None and page_size_kb > 1200:
        attention_perf.append(f"\u26a0 HTML pesado (~{page_size_kb} KB).")
    if not cdn_hints:
        attention_perf.append("\u26a0 CDN/cache: requer validacao.")

    problema_critico, impacto = _critical_problem(signals)
    indexacao = _paths_summary(pages)

    deficiencias = []
    if not has_canonical:
        deficiencias.append("\u26a0 Canonical ausente.")
    if not meta_description:
        deficiencias.append("\u26a0 Meta description ausente.")
    if not has_schema:
        deficiencias.append("\u26a0 Schema JSON-LD nao identificado.")
    if not has_og:
        deficiencias.append("\u26a0 OG tags ausentes.")
    if h1_count != 1:
        deficiencias.append("\u26a0 Estrutura de headings (H1) fora do ideal.")
    if indexable is False:
        deficiencias.append("\u26a0 Meta robots indica noindex.")
    if word_count and word_count < 200:
        deficiencias.append("\u26a0 Sinais de thin content (baixo volume de texto).")
    if internal_links_count == 0:
        deficiencias.append("\u26a0 Poucos ou nenhum link interno identificado.")

    risco = []
    if duplicate_home:
        risco.append("\U0001F534 Canibalizacao de relevancia entre paginas duplicadas.")
    if not meta_description:
        risco.append("\U0001F534 Snippet menos atrativo vs concorrentes.")
    if not has_schema:
        risco.append("\U0001F534 Menor rich results e visibilidade em SERP.")

    if nav_items:
        nav_summary = ", ".join(nav_items)
        navegacao_line = f"Menu com {len(nav_items)} itens: {nav_summary}"
    else:
        internal_links = page.get("internal_links_count")
        if internal_links is None:
            navegacao_line = "Menu nao identificado."
        else:
            navegacao_line = f"Menu nao identificado; links internos: {internal_links}"

    conversao = []
    if cta_texts:
        conversao.append("\u2705 CTAs: " + ", ".join(cta_texts[:4]))
    if has_form:
        conversao.append("\u2705 Formulario de contato detectado.")
    if has_whatsapp:
        conversao.append("\u2705 Botao/contato via WhatsApp.")
    if not conversao:
        conversao = [
            "\u26a0 Nenhum CTA ou formulario visivel.",
            "\u26a0 Recomenda-se CTA principal acima da dobra.",
        ]

    content_depth = word_count >= 250 and section_count >= 3
    jornada_line = _journey_line(bool(cta_texts or has_form or has_whatsapp), content_depth, nav_items)

    lacunas_ux = []
    if section_count < 3:
        lacunas_ux.append("\u26a0 Poucas se\u00e7\u00f5es de conteudo.")
    if not has_faq:
        lacunas_ux.append("\u26a0 FAQ ausente (duvidas nao respondidas).")
    if not has_gallery:
        lacunas_ux.append("\u26a0 Galeria ou provas visuais nao evidenciadas.")
    lacunas_ux = _ensure(lacunas_ux, "\u26a0 Lacunas informacionais requerem validacao.")

    positivo_a11y = []
    if images_missing_alt == 0 and page.get("images_total", 0) > 0:
        positivo_a11y.append("\u2705 Imagens com alt presentes.")
    if h1_count == 1:
        positivo_a11y.append("\u2705 H1 unico melhora leitura semantica.")
    positivo_a11y = _ensure(positivo_a11y, "\u2705 Requer validacao de acessibilidade basica.")

    validar_a11y = []
    if images_missing_alt > 0:
        validar_a11y.append(f"\u26a0 {images_missing_alt} imagens sem alt.")
    validar_a11y.append("\u26a0 Contraste e navegacao por teclado requerem validacao.")
    validar_a11y.append("\u26a0 Atributos ARIA e foco visivel precisam de revisao.")

    comunicacao = []
    if h1_text:
        comunicacao.append(f"\"{h1_text}\"")
    elif page.get("title"):
        comunicacao.append(f"\"{page.get('title')}\"")
    else:
        comunicacao.append("Sem evidencias de mensagem aspiracional; requer validacao.")

    dados_concretos = []
    if number_samples:
        dados_concretos.append("Dados encontrados: " + ", ".join(number_samples))
    else:
        dados_concretos.append("Sem evidencias de dados concretos; requer validacao.")

    lacunas_conv = []
    if not has_testimonials:
        lacunas_conv.append("\u26a0 Prova social/depoimentos nao encontrados.")
    if not has_pricing:
        lacunas_conv.append("\u26a0 Faixa de pre\u00e7o ou investimento nao evidenciada.")
    if not has_numbers:
        lacunas_conv.append("\u26a0 Poucos dados numericos de suporte.")
    lacunas_conv = _ensure(lacunas_conv, "\u26a0 Lacunas criticas requerem validacao.")

    pontos_fortes = []
    if ssl:
        pontos_fortes.append("\u2705 HTTPS ativo e ambiente seguro.")
    if has_viewport:
        pontos_fortes.append("\u2705 Estrutura responsiva detectada.")
    if cta_texts or has_form or has_whatsapp:
        pontos_fortes.append("\u2705 Possui pontos de conversao claros.")
    if meta_description:
        pontos_fortes.append("\u2705 Meta description presente.")
    pontos_fortes = _ensure(pontos_fortes, "\u2705 Requer validacao para confirmar pontos fortes.")

    perf_gargalos = []
    if images_total >= 12:
        perf_gargalos.append("\U0001F534 Volume alto de imagens sem otimizacao comprovada.")
    if render_blocking > 0:
        perf_gargalos.append("\U0001F534 Scripts bloqueando renderizacao.")
    if not cdn_hints:
        perf_gargalos.append("\U0001F534 CDN/cache nao evidenciados.")
    perf_gargalos = _ensure(perf_gargalos, "\U0001F534 Gargalos de performance requerem validacao.")

    seo_gargalos = []
    if duplicate_home:
        seo_gargalos.append("\U0001F534 Duplicidade entre / e /home.")
    if not has_canonical:
        seo_gargalos.append("\U0001F534 Canonical ausente.")
    if not has_schema:
        seo_gargalos.append("\U0001F534 Schema nao implementado.")
    if not meta_description:
        seo_gargalos.append("\U0001F534 Meta description ausente.")
    seo_gargalos = _ensure(seo_gargalos, "\U0001F534 Gargalos de SEO requerem validacao.")

    ux_gargalos = []
    if section_count < 3:
        ux_gargalos.append("\U0001F534 Conteudo raso e pouca profundidade informacional.")
    if not has_gallery:
        ux_gargalos.append("\U0001F534 Falta de galeria/visual para decisao.")
    if not has_faq:
        ux_gargalos.append("\U0001F534 Ausencia de FAQ reduz clareza.")
    ux_gargalos = _ensure(ux_gargalos, "\U0001F534 Gargalos de UX requerem validacao.")

    conv_gargalos = []
    if not (cta_texts or has_form or has_whatsapp):
        conv_gargalos.append("\U0001F534 Poucos pontos de captura de lead.")
    if not has_testimonials:
        conv_gargalos.append("\U0001F534 Ausencia de prova social.")
    if not has_pricing:
        conv_gargalos.append("\U0001F534 Transparencia de preco insuficiente.")
    conv_gargalos = _ensure(conv_gargalos, "\U0001F534 Gargalos de conversao requerem validacao.")

    seo_gaps = []
    if not has_schema or not has_canonical:
        seo_gaps.append("sitemap")

    conversion_gaps = []
    if not has_testimonials or not has_pricing:
        conversion_gaps.append("chatbot")
    if is_real_estate:
        conversion_gaps.append("pos_venda")

    signals["seo_gaps"] = seo_gaps
    signals["conversion_gaps"] = conversion_gaps

    oportunidades = _build_opportunities(signals)

    situacao_atual = []
    if ssl:
        situacao_atual.append("\u2713 HTTPS ativo e site acessivel.")
    if meta_description:
        situacao_atual.append("\u2713 Base de SEO presente, mas incompleta.")
    if cta_texts or has_form or has_whatsapp:
        situacao_atual.append("\u2713 Possui pontos iniciais de conversao.")
    situacao_atual = _ensure(situacao_atual, "\u2713 Situa\u00e7\u00e3o atual requer validacao.")

    desafios = []
    if not has_canonical:
        desafios.append("\u26a0 Resolver bases de SEO tecnico (canonical/schema).")
    if images_total >= 12 or render_blocking > 0:
        desafios.append("\u26a0 Melhorar performance e peso da pagina.")
    if not has_testimonials:
        desafios.append("\u26a0 Reforcar prova social e argumentos concretos.")
    desafios = _ensure(desafios, "\u26a0 Desafios requerem validacao.")

    necessidade = [
        "\u2192 Corrigir fundamentos de SEO tecnico e evitar duplicacao.",
        "\u2192 Otimizar performance e experiencia mobile.",
        "\u2192 Fortalecer prova social e conteudos de conversao.",
    ]

    scores_data = result.get("scores") or {}
    overall = scores_data.get("overall", "-")
    seo_score = scores_data.get("SEO", "-")
    a11y_score = scores_data.get("A11Y", "-")
    content_score = scores_data.get("CONTENT", "-")
    scores_lines = [
        f"Overall: {overall}",
        f"SEO: {seo_score} | A11Y: {a11y_score} | CONTENT: {content_score}",
    ]

    slide2 = Slide2(
        contexto=contexto,
        conceito=conceito,
        infraestrutura=infraestrutura,
        presenca_digital=presenca,
        scores=scores_lines,
    )
    slide3 = Slide3(
        pontos_positivos=_ensure(pos_perf, "\u2705 Requer validacao de performance."),
        pontos_atencao=_ensure(attention_perf, "\u26a0 Requer validacao de performance."),
    )
    slide4 = Slide4(
        problema_critico=problema_critico,
        impacto=impacto,
        indexacao=indexacao,
        deficiencias=_ensure(deficiencias, "\u26a0 Sem deficiencias criticas confirmadas."),
        risco_competitivo=_ensure(risco, "\U0001F534 Risco competitivo requer validacao."),
    )
    slide5 = Slide5(
        navegacao=navegacao_line,
        conversao=conversao,
        jornada=jornada_line,
        lacunas=lacunas_ux,
    )
    slide6 = Slide6(positivo=positivo_a11y, requer_validacao=validar_a11y)
    slide7 = Slide7(
        comunicacao=comunicacao,
        dados_concretos=dados_concretos,
        lacunas=lacunas_conv,
    )
    slide8 = Slide8(pontos_fortes=pontos_fortes)
    slide9 = Slide9(
        performance=perf_gargalos,
        seo=seo_gargalos,
        ux=ux_gargalos,
        conversao=conv_gargalos,
    )
    slide10 = Slide10(acoes=oportunidades)
    slide11 = Slide11(
        situacao_atual=situacao_atual,
        desafios=desafios,
        necessidade=necessidade,
    )

    return ReportSlides(
        slide2=slide2,
        slide3=slide3,
        slide4=slide4,
        slide5=slide5,
        slide6=slide6,
        slide7=slide7,
        slide8=slide8,
        slide9=slide9,
        slide10=slide10,
        slide11=slide11,
    )


def render_report(slides: ReportSlides) -> str:
    lines: list[str] = []
    bullet = lambda items: [f"- {item}" for item in items]

    lines.append("VIS\u00c3O GERAL DO SITE")
    lines.append("Contexto:")
    lines.extend(bullet(slides.slide2.contexto))
    lines.append("Conceito:")
    lines.extend(bullet(slides.slide2.conceito))
    lines.append("Infraestrutura:")
    lines.extend(bullet(slides.slide2.infraestrutura))
    lines.append("Presen\u00e7a Digital:")
    lines.extend(bullet(slides.slide2.presenca_digital))
    lines.append("Scores:")
    lines.extend(bullet(slides.slide2.scores))
    lines.append("")

    lines.append("PERFORMANCE T\u00c9CNICA")
    lines.append("Pontos Positivos:")
    lines.extend(bullet(slides.slide3.pontos_positivos))
    lines.append("Pontos de Aten\u00e7\u00e3o:")
    lines.extend(bullet(slides.slide3.pontos_atencao))
    lines.append("")

    lines.append("SEO ON-PAGE \u2014 PROBLEMAS CR\u00cdTICOS")
    lines.append(f"PROBLEMA CR\u00cdTICO: {slides.slide4.problema_critico}")
    lines.append(f"Impacto: {slides.slide4.impacto}")
    lines.append(f"Indexa\u00e7\u00e3o no Google: {slides.slide4.indexacao}")
    lines.append("Defici\u00eancias Identificadas:")
    lines.extend(bullet(slides.slide4.deficiencias))
    lines.append("Risco Competitivo:")
    lines.extend(bullet(slides.slide4.risco_competitivo))
    lines.append("")

    lines.append("EXPERI\u00caNCIA DO USU\u00c1RIO (UX)")
    lines.append(f"Navega\u00e7\u00e3o: {slides.slide5.navegacao}")
    lines.append("Elementos de Convers\u00e3o:")
    lines.extend(bullet(slides.slide5.conversao))
    lines.append(f"Jornada do Usu\u00e1rio: {slides.slide5.jornada}")
    lines.append("Lacuna Informacional:")
    lines.extend(bullet(slides.slide5.lacunas))
    lines.append("")

    lines.append("ACESSIBILIDADE")
    lines.append("Positivo:")
    lines.extend(bullet(slides.slide6.positivo))
    lines.append("Requer Valida\u00e7\u00e3o:")
    lines.extend(bullet(slides.slide6.requer_validacao))
    lines.append("")

    lines.append("CONVERS\u00c3O E COMUNICA\u00c7\u00c3O")
    lines.append("Comunica\u00e7\u00e3o Emocional (Messaging Aspiracional):")
    lines.extend(bullet(slides.slide7.comunicacao))
    lines.append("Dados Concretos (Argumenta\u00e7\u00e3o Racional):")
    lines.extend(bullet(slides.slide7.dados_concretos))
    lines.append("Lacunas Cr\u00edticas:")
    lines.extend(bullet(slides.slide7.lacunas))
    lines.append("")

    lines.append("PONTOS FORTES")
    lines.extend(bullet(slides.slide8.pontos_fortes))
    lines.append("")

    lines.append("GARGALOS CR\u00cdTICOS")
    lines.append("1. Performance T\u00e9cnica:")
    lines.extend(bullet(slides.slide9.performance))
    lines.append("2. SEO e Visibilidade:")
    lines.extend(bullet(slides.slide9.seo))
    lines.append("3. Experi\u00eancia do Usu\u00e1rio:")
    lines.extend(bullet(slides.slide9.ux))
    lines.append("4. Convers\u00e3o:")
    lines.extend(bullet(slides.slide9.conversao))
    lines.append("")

    lines.append(f"OPORTUNIDADES ESTRAT\u00c9GICAS ({len(slides.slide10.acoes)} a\u00e7\u00f5es)")
    for idx, action in enumerate(slides.slide10.acoes, start=1):
        lines.append(f"{idx}) {action}")
    lines.append("")

    lines.append("DIAGN\u00d3STICO CONSOLIDADO")
    lines.append("Situa\u00e7\u00e3o Atual:")
    lines.extend(bullet(slides.slide11.situacao_atual))
    lines.append("Principais Desafios:")
    lines.extend(bullet(slides.slide11.desafios))
    lines.append("Necessidade Principal:")
    lines.extend(slides.slide11.necessidade)
    # Rodape removido conforme solicitado.

    return "\n".join(lines).strip()


def generate_report(
    result: dict,
    context: Optional[dict] = None,
) -> str:
    slides = build_report_slides(result, context=context)
    return render_report(slides)
