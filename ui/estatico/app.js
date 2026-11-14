"use strict";
/* Interface local do class2md. Sem biblioteca, sem rede externa.
   Todo texto vindo de arquivo, nota ou erro entra na página por textContent (S7). */
(function () {
  const TOKEN = (document.querySelector('meta[name="class2md-token"]') || {}).content || "";
  const REGEX_DISCIPLINA = /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/;
  const PASSOS = ["O que fazer", "Arquivos", "Custo e tempo", "Acompanhar", "Revisar"];
  const ABAS = ["processar", "notas", "economia", "ajuda"];
  const MATERIAIS = [
    ["foto_aula", "Fotos da aula", "Lousa, projeção ou caderno"],
    ["pdf_livro", "PDF de livro inteiro", "O livro da disciplina, para consultar depois"],
    ["pdf_capitulos", "PDF por capítulos", "Um capítulo ou alguns, já separados"],
    ["pdf_lista", "Lista de exercícios em PDF", "Entra como material da aula. O class2md não resolve a lista"],
  ];
  const COMANDOS_PDF = {
    pdf_livro: [
      "Coloque o PDF em estudos/pdfs/<Disciplina>/livros/ e rode:",
      "uv run python scripts/estudos.py indexar-pdf",
      "Monta o índice de capítulos uma vez. Custa uma chamada pequena.",
    ],
    pdf_capitulos: [
      "Depois de indexar o livro, consulte só os capítulos que quiser para as dúvidas de uma nota:",
      "uv run python scripts/estudos.py preencher-lacunas <execução> --capitulo 3",
      "",
    ],
    pdf_lista: [
      "Registre a lista ligada ao dia da aula:",
      "uv run python scripts/estudos.py indexar-pdf caminho/da/lista.pdf --tipo exercicios --data-aula AAAA-MM-DD",
      "Ela entra como material na nota daquela aula.",
    ],
  };
  const SITUACAO_ETAPA = {
    espera: ["○", "Na fila"],
    rodando: ["◌", "Rodando"],
    feito: ["✓", "Feito"],
    guardado: ["✓", "Feito, resultado guardado"],
    aviso: ["▲", "Feito, com aviso"],
    falhou: ["✕", "Falhou"],
    pulada: ["–", "Não pedida"],
  };
  const SITUACAO_NOTA = {
    concluido: "Concluída", parcial: "Parcial", aguardando_humano: "Aguardando resposta",
    falhou: "Falhou", promovido: "Promovida", na_fila: "Na fila", rodando: "Rodando",
  };

  const S = {
    estado: null,
    material: null,
    etapas: new Set(),
    planos: {},
    disciplina: "",
    outra: false,
    envio: { id: null, arquivos: [], pasta: "" },
    estimativa: null,
    jobId: null,
    execucao: null,
    notaId: null,
    foco: null,
    timer: null,
  };

  // ------------------------------------------------------------------ utilidades
  function h(tag, props, ...filhos) {
    const el = document.createElement(tag);
    for (const [chave, valor] of Object.entries(props || {})) {
      if (valor === null || valor === undefined || valor === false) continue;
      if (chave === "class") el.className = valor;
      else if (chave === "text") el.textContent = valor;
      else if (chave === "on") for (const [ev, fn] of Object.entries(valor)) el.addEventListener(ev, fn);
      else el.setAttribute(chave, valor === true ? "" : valor);
    }
    for (const filho of filhos.flat()) {
      if (filho === null || filho === undefined || filho === false) continue;
      el.append(filho.nodeType ? filho : document.createTextNode(String(filho)));
    }
    return el;
  }
  const $ = (id) => document.getElementById(id);
  function anunciar(texto) {
    const alvo = $("vf-anuncio");
    alvo.textContent = "";
    setTimeout(() => { alvo.textContent = texto; }, 30);
  }
  function usd(n) {
    if (n === null || n === undefined) return "sem estimativa";
    const casas = n > 0 && n < 0.01 ? 4 : 2;
    return "US$ " + n.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
  }
  function segundos(n) {
    if (n === null || n === undefined) return "sem estimativa";
    if (n < 60) return Math.round(n) + " s";
    return Math.floor(n / 60) + " min " + Math.round(n % 60) + " s";
  }
  function mb(bytes) { return (bytes / (1024 * 1024)).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " MB"; }
  function guardar(chave, valor) { try { sessionStorage.setItem(chave, valor); } catch (e) { /* sem armazenamento */ } }
  function ler(chave) { try { return sessionStorage.getItem(chave); } catch (e) { return null; } }

  async function api(metodo, caminho, corpo) {
    const opcoes = { method: metodo, headers: {} };
    if (metodo !== "GET") opcoes.headers["X-Class2md-Token"] = TOKEN;
    if (corpo instanceof FormData) opcoes.body = corpo;
    else if (corpo !== undefined) {
      opcoes.headers["Content-Type"] = "application/json";
      opcoes.body = JSON.stringify(corpo);
    }
    let resposta;
    try { resposta = await fetch(caminho, opcoes); }
    catch (e) { throw new Error("O pedido não chegou ao programa. Confira se o comando ui continua rodando no terminal."); }
    let dados = {};
    try { dados = await resposta.json(); } catch (e) { /* corpo não é JSON */ }
    if (!resposta.ok) {
      const erro = new Error(dados.mensagem || "Algo deu errado.");
      erro.codigo = dados.erro;
      erro.status = resposta.status;
      throw erro;
    }
    return dados;
  }

  function codigo(texto, rotulo) {
    const botao = h("button", { class: "vf-copiar", type: "button" }, icone("copiar", "vf-icone--p"), " Copiar");
    botao.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(texto); } catch (e) { /* sem permissão */ }
      botao.replaceChildren(icone("feito", "vf-icone--p"), " Copiado");
      anunciar("Copiado");
      setTimeout(() => { botao.replaceChildren(icone("copiar", "vf-icone--p"), " Copiar"); }, 2000);
    });
    return h("div", { class: "vf-codigo" },
      h("div", { class: "vf-codigo-topo" }, h("span", { class: "vf-codigo-rotulo", text: rotulo || "Comando" }), botao),
      h("pre", {}, h("code", { text: texto })));
  }
  function icone(nome, extra) {
    const no = $("molde-icone").content.firstElementChild.cloneNode(true);
    no.querySelector("use").setAttribute("href", "/estatico/icones.svg#" + nome);
    if (extra) no.classList.add(extra);
    return no;
  }
  function estadoCaixa(tipo, titulo, texto, papel) {
    const nome = { erro: "erro", aviso: "aviso", sucesso: "feito" }[tipo];
    return h("div", { class: "vf-estado vf-estado--" + tipo, role: papel || (tipo === "erro" ? "alert" : "status") },
      nome ? icone(nome) : null, h("p", {}, titulo ? h("strong", { text: titulo + " " }) : null, texto));
  }
  function tabela(legenda, cabecalhos, linhas, classe) {
    return h("div", { class: "vf-tabela-rolagem" },
      h("table", { class: "vf-tabela" + (classe ? " " + classe : "") },
        h("caption", { text: legenda }),
        h("thead", {}, h("tr", {}, cabecalhos.map((c) => h("th", { scope: "col", text: c })))),
        h("tbody", {}, linhas.map((l) => h("tr", {}, l.map((c, i) =>
          h(i === 0 ? "th" : "td", i === 0 ? { scope: "row" } : { "data-rotulo": cabecalhos[i] }, c)))))));
  }
  function botao(texto, aoClicar, opcoes) {
    const o = opcoes || {};
    return h("button", {
      class: "vf-botao" + (o.primario ? " vf-botao--primario" : "") + (o.discreto ? " vf-botao--discreto" : ""),
      type: "button", disabled: o.desabilitado, "aria-describedby": o.motivoId,
      on: { click: aoClicar },
    }, o.icone ? icone(o.icone, "vf-icone--p") : null, o.icone ? " " : null, texto, o.oculto ? h("span", { class: "vf-oculto", text: " " + o.oculto }) : null);
  }
  function acoes(motivoId, motivoTexto, ...botoes) {
    return h("div", { class: "vf-acoes" }, ...botoes,
      motivoTexto ? h("p", { class: "vf-acoes-motivo", id: motivoId, text: motivoTexto }) : null);
  }
  function confirmar({ titulo, texto, rotuloOk }) {
    return new Promise((resolver) => {
      const cancelar = h("button", { class: "vf-botao", type: "button" }, "Cancelar");
      const ok = h("button", { class: "vf-botao vf-botao--primario", type: "button" }, rotuloOk || "Continuar");
      const dialogo = h("dialog", { class: "vf-dialogo", "aria-labelledby": "dlg-titulo" },
        h("h2", { class: "vf-dialogo-titulo", id: "dlg-titulo", text: titulo }),
        h("p", { text: texto }), h("div", { class: "vf-acoes" }, cancelar, ok));
      const fechar = (valor) => { dialogo.close(); dialogo.remove(); resolver(valor); };
      cancelar.addEventListener("click", () => fechar(false));
      ok.addEventListener("click", () => fechar(true));
      dialogo.addEventListener("cancel", (e) => { e.preventDefault(); fechar(false); });
      document.body.append(dialogo);
      dialogo.showModal();
      cancelar.focus();
    });
  }

  // ------------------------------------------------------------------ navegação
  function destino() {
    const [aba, passo] = (location.hash || "#processar/1").slice(1).split("/");
    return { aba: ABAS.includes(aba) ? aba : "processar", passo: Math.min(Math.max(parseInt(passo, 10) || 1, 1), 5) };
  }
  function ir(aba, passo) {
    const novo = "#" + aba + (aba === "processar" ? "/" + (passo || 1) : "");
    if (location.hash === novo) render(); else location.hash = novo;
  }
  function pararConsulta() { if (S.timer) { clearTimeout(S.timer); S.timer = null; } }

  function montarAbas() {
    const lista = document.querySelector(".vf-abas-lista");
    const botoes = [...lista.querySelectorAll('[role="tab"]')];
    botoes.forEach((b, i) => {
      b.addEventListener("click", () => ir(ABAS[i], 1));
      b.addEventListener("keydown", (e) => {
        let j = null;
        if (e.key === "ArrowRight") j = (i + 1) % botoes.length;
        else if (e.key === "ArrowLeft") j = (i - 1 + botoes.length) % botoes.length;
        else if (e.key === "Home") j = 0;
        else if (e.key === "End") j = botoes.length - 1;
        if (j !== null) { e.preventDefault(); botoes[j].focus(); ir(ABAS[j], 1); }
      });
    });
    document.querySelector(".vf-abas").setAttribute("data-vf-pronto", "");
  }

  function titulo(texto) {
    const t = h("h2", { tabindex: "-1", text: texto });
    return t;
  }
  function indicadorDePassos(atual) {
    return h("ol", { class: "vf-passos", "aria-label": "Passos" }, PASSOS.map((nome, i) => {
      const n = i + 1;
      const feito = n < atual;
      return h("li", { class: "vf-passo", "aria-current": n === atual ? "step" : null, "data-feito": feito },
        h("span", { class: "vf-passo-num" }, feito ? icone("feito") : String(n)),
        feito ? h("span", { class: "vf-oculto", text: "feito " }) : null,
        h("span", { class: "vf-passo-nome", text: nome }));
    }));
  }

  function render() {
    pararConsulta();
    const { aba, passo } = destino();
    ABAS.forEach((nome) => {
      const selecionada = nome === aba;
      const tab = $("aba-" + nome);
      tab.setAttribute("aria-selected", String(selecionada));
      tab.tabIndex = selecionada ? 0 : -1;
      $("painel-" + nome).hidden = !selecionada;
    });
    const painel = $("painel-" + aba);
    painel.replaceChildren();
    const montadores = { processar: () => telaProcessar(painel, passo), notas: () => telaNotas(painel), economia: () => telaEconomia(painel), ajuda: () => telaAjuda(painel) };
    Promise.resolve(montadores[aba]()).then(() => {
      const alvo = S.foco && $(S.foco) ? $(S.foco) : painel.querySelector("h2");
      S.foco = null;
      if (alvo) alvo.focus();
    });
  }

  // ------------------------------------------------------------------- topo
  async function carregarEstado() {
    S.estado = await api("GET", "/api/estado");
    $("est-chave").textContent = S.estado.chave_configurada ? "configurada" : "não configurada";
    $("est-gasto").textContent = S.estado.teto_usd === null ? "sem dado"
      : usd(S.estado.gasto_mes_usd) + " de " + usd(S.estado.teto_usd);
  }

  // --------------------------------------------------------------- processar
  async function telaProcessar(painel, passo) {
    if (!S.estado.chave_configurada) return telaSemChave(painel);
    if (passo > 1 && !S.material && passo < 4) { ir("processar", 1); return; }
    if (passo === 4 && !S.jobId) { S.jobId = ler("jobId"); if (!S.jobId) { ir("processar", 1); return; } }
    if (passo === 5 && !S.notaId) { ir("processar", 1); return; }
    painel.append(indicadorDePassos(passo));
    const passos = [passo1, passo2, passo3, passo4, passo5];
    await passos[passo - 1](painel);
    anunciar("Passo " + passo + " de 5: " + PASSOS[passo - 1]);
  }

  function telaSemChave(painel) {
    painel.append(
      h("h2", { tabindex: "-1", text: "Falta a chave da API" }),
      h("p", { text: "O class2md usa a API da Anthropic, que é paga. A chave fica só neste computador." }),
      h("ol", {},
        h("li", { text: "Crie uma chave em console.anthropic.com, em Settings, API keys." }),
        h("li", {}, "Na pasta do projeto, copie o arquivo de exemplo:", codigo("cp .env.example .env")),
        h("li", { text: "Abra o .env e preencha ANTHROPIC_API_KEY." }),
        h("li", {}, "Pare este programa com Ctrl+C e rode de novo:", codigo("uv run python scripts/estudos.py ui"))),
      h("p", { text: "A página não tem campo para digitar a chave. Assim ela nunca passa pelo navegador." }),
      h("div", { id: "aviso-chave" }),
      botao("Já configurei, verificar de novo", async () => {
        await carregarEstado();
        if (S.estado.chave_configurada) render();
        else $("aviso-chave").replaceChildren(estadoCaixa("aviso", "", "Ainda não encontrei a chave. Confira se o arquivo se chama .env e está na pasta do projeto."));
      }));
  }

  async function planoDe(material) {
    if (!S.planos[material]) S.planos[material] = await api("GET", "/api/plano?material=" + encodeURIComponent(material));
    return S.planos[material];
  }
  function faltantes(plano, escolhidas) {
    const por = Object.fromEntries(plano.etapas.map((e) => [e.nome, e]));
    const falta = new Set();
    const visitar = (nome) => por[nome].depende_de.forEach((d) => { if (!escolhidas.has(d)) falta.add(d); visitar(d); });
    escolhidas.forEach(visitar);
    return [...falta];
  }

  async function passo1(painel) {
    painel.append(titulo("O que você quer fazer?"),
      h("p", { text: "Escolha o material e marque as etapas que quer. Nada vem marcado, e nada roda antes de você confirmar o custo." }));
    const materiais = h("fieldset", { class: "vf-opcoes" }, h("legend", { text: "Que material você tem?" }),
      MATERIAIS.map(([valor, nome, desc]) => {
        const radio = h("input", { type: "radio", name: "material", value: valor, id: "mat-" + valor, checked: S.material === valor });
        radio.addEventListener("change", () => { S.material = valor; S.etapas = new Set(); S.foco = "mat-" + valor; render(); });
        return h("label", { class: "vf-opcao", for: "mat-" + valor }, radio,
          icone("m-" + valor, "vf-opcao-icone"),
          h("span", { class: "vf-opcao-titulo", text: nome }),
          h("span", { class: "vf-opcao-descricao", text: desc }),
          h("span", { class: "vf-opcao-marca", "aria-hidden": "true" }, icone("feito")));
      }));
    painel.append(materiais);
    if (!S.material) { painel.append(acoes("motivo-1", "Escolha o material.", botao("Continuar", () => {}, { primario: true, desabilitado: true, motivoId: "motivo-1" }))); return; }
    const plano = await planoDe(S.material);
    if (!plano.disponivel) {
      const [intro, cmd, nota] = COMANDOS_PDF[S.material];
      painel.append(h("div", { class: "vf-cartao" },
        h("h3", {}, icone("terminal", "vf-icone--p"), " Disponível pela linha de comando"), h("span", { class: "vf-marca", text: "Na tela: em desenvolvimento" }),
        h("p", { text: intro }), codigo(cmd), nota ? h("p", { text: nota }) : null));
      return;
    }
    painel.append(listaDeEtapas(plano));
    const falta = faltantes(plano, S.etapas);
    let motivo = null;
    if (S.etapas.size === 0) motivo = "Marque pelo menos uma etapa.";
    else if (falta.length) motivo = "Resolva o aviso acima para continuar.";
    painel.append(acoes("motivo-1", motivo, botao("Continuar", () => ir("processar", 2), { primario: true, desabilitado: !!motivo, motivoId: motivo ? "motivo-1" : null })));
  }

  function listaDeEtapas(plano) {
    const nomes = Object.fromEntries(plano.etapas.map((e) => [e.nome, e.rotulo]));
    const todas = S.etapas.size === plano.etapas.length;
    const marcarTodas = h("button", { class: "vf-marcar-todas", type: "button", id: "marcar-todas",
      on: { click: () => { S.etapas = todas ? new Set() : new Set(plano.etapas.map((e) => e.nome)); S.foco = "marcar-todas"; render(); } } },
      icone(todas ? "desmarcar-todas" : "marcar-todas"), todas ? " Desmarcar todas as etapas" : " Marcar todas as etapas");
    const grupo = h("fieldset", { class: "vf-etapas" }, h("legend", { text: "Etapas" }),
      h("div", { class: "vf-marcar-bloco" }, marcarTodas),
      plano.etapas.map((e) => {
        const caixa = h("input", { type: "checkbox", id: "et-" + e.nome, name: "etapas", value: e.nome, checked: S.etapas.has(e.nome),
          "aria-describedby": "et-" + e.nome + "-d" + (e.depende_de.length ? " et-" + e.nome + "-s" : "") });
        caixa.addEventListener("change", () => {
          if (caixa.checked) S.etapas.add(e.nome); else S.etapas.delete(e.nome);
          S.foco = "et-" + e.nome; render();
        });
        return h("div", { class: "vf-etapa" }, caixa, h("label", { for: "et-" + e.nome, text: e.rotulo }),
          h("p", { class: "vf-etapa-descricao", id: "et-" + e.nome + "-d", text: e.descricao }),
          e.depende_de.length ? h("p", { class: "vf-etapa-situacao", id: "et-" + e.nome + "-s", text: "Precisa de: " + e.depende_de.map((d) => nomes[d]).join(", ") + "." }) : null);
      }));
    const bloco = h("div", {}, grupo);
    const falta = faltantes(plano, S.etapas);
    if (falta.length) {
      const dependentes = [...S.etapas].filter((n) => plano.etapas.find((e) => e.nome === n).depende_de.some((d) => !S.etapas.has(d)));
      bloco.append(h("div", { class: "vf-estado vf-estado--aviso", role: "alert" }, icone("aviso"),
        h("p", {}, h("strong", { text: dependentes.map((n) => nomes[n]).join(", ") }), " precisa de ", h("strong", { text: falta.map((n) => nomes[n]).join(" e ") }), "."),
        h("div", { class: "vf-acoes" },
          botao("Incluir as que faltam", () => { falta.forEach((n) => S.etapas.add(n)); render(); }),
          botao("Desmarcar as que precisam delas", () => {
            let mudou = true;
            while (mudou) {
              mudou = false;
              for (const n of [...S.etapas]) {
                if (plano.etapas.find((e) => e.nome === n).depende_de.some((d) => !S.etapas.has(d))) { S.etapas.delete(n); mudou = true; }
              }
            }
            render();
          }))));
    }
    return bloco;
  }

  // ----------------------------------------------------------------- passo 2
  async function passo2(painel) {
    const est = S.estado;
    painel.append(titulo("Quais arquivos?"));
    const travado = S.envio.arquivos.length > 0;
    let campo;
    const erro = h("p", { class: "vf-campo-erro", id: "disc-erro", hidden: true, text: "Use só letras, números, ponto, hífen e sublinhado. Até 32 caracteres." });
    const checar = () => {
      const ok = REGEX_DISCIPLINA.test(S.disciplina);
      erro.hidden = ok || S.disciplina === "";
      if (ok || S.disciplina === "") campo.removeAttribute("aria-invalid"); else campo.setAttribute("aria-invalid", "true");
      return ok;
    };
    const entradaTexto = h("input", { class: "vf-entrada", type: "text", id: "disciplina", value: S.disciplina, maxlength: "32", disabled: travado,
      "aria-describedby": "disc-ajuda disc-erro", autocomplete: "off" });
    entradaTexto.addEventListener("input", () => { S.disciplina = entradaTexto.value.trim(); checar(); atualizar(); });
    if (est.tem_registro && est.disciplinas.length && !S.outra) {
      campo = h("select", { class: "vf-entrada", id: "disciplina", disabled: travado, "aria-describedby": "disc-ajuda disc-erro" },
        h("option", { value: "", text: "Escolha…" }),
        est.disciplinas.map((d) => h("option", { value: d, selected: d === S.disciplina, text: d })),
        h("option", { value: "__outra", text: "Outra…" }));
      campo.addEventListener("change", () => {
        if (campo.value === "__outra") { S.outra = true; S.disciplina = ""; S.foco = "disciplina"; render(); return; }
        S.disciplina = campo.value; checar(); atualizar();
      });
    } else campo = entradaTexto;
    painel.append(h("div", { class: "vf-campo" }, h("label", { class: "vf-campo-rotulo", for: "disciplina", text: "Disciplina" }),
      h("p", { class: "vf-campo-ajuda", id: "disc-ajuda", text: "Vira o nome da pasta das notas. Use letras, números, hífen e sublinhado, sem espaço." }), campo, erro));

    const entrada = h("input", { class: "vf-oculto", type: "file", id: "arquivos", multiple: true, accept: "image/jpeg,image/png", "aria-describedby": "arquivos-ajuda" });
    const area = h("div", { class: "vf-soltar", id: "soltar" },
      icone("enviar", "vf-icone--gg"),
      h("p", { class: "vf-soltar-texto", text: "Arraste as fotos para cá" }),
      h("label", { class: "vf-botao", for: "arquivos" }, "Escolher arquivos"), entrada,
      h("p", { class: "vf-soltar-ajuda", id: "arquivos-ajuda", text: "JPEG ou PNG. Até " + Math.round(est.limites.max_foto_bytes / 1048576) + " MB por foto e " + est.limites.max_fotos_por_envio + " fotos por envio." }));
    ["dragenter", "dragover"].forEach((ev) => area.addEventListener(ev, (e) => { e.preventDefault(); area.setAttribute("data-vf-sobre", ""); }));
    ["dragleave", "drop"].forEach((ev) => area.addEventListener(ev, (e) => { e.preventDefault(); area.removeAttribute("data-vf-sobre"); }));
    area.addEventListener("drop", (e) => enviar([...e.dataTransfer.files]));
    entrada.addEventListener("change", () => enviar([...entrada.files]));
    painel.append(area, h("div", { id: "envio-estado" }), h("div", { id: "envio-lista" }));

    async function enviar(arquivos) {
      if (!arquivos.length) return;
      if (!checar() || !S.disciplina) { erro.hidden = false; anunciar("Escolha a disciplina antes de enviar."); (campo.focus && campo.focus()); return; }
      const caixa = $("envio-estado");
      caixa.replaceChildren(h("p", { class: "vf-estado vf-estado--carregando", role: "status", text: "Enviando " + arquivos.length + " arquivos…" }));
      const dados = new FormData();
      dados.append("disciplina", S.disciplina);
      if (S.envio.id) dados.append("envio_id", S.envio.id);
      arquivos.forEach((a) => dados.append("arquivos", a, a.name));
      try {
        const r = await api("POST", "/api/materiais", dados);
        S.envio.id = r.envio_id; S.envio.pasta = r.pasta;
        S.envio.arquivos.push(...r.arquivos);
        const ok = r.arquivos.filter((a) => a.situacao !== "recusado").length;
        const nao = r.arquivos.length - ok;
        const texto = nao ? ok + " recebidos, " + nao + " recusados. Veja o motivo na lista." : ok + " arquivos recebidos.";
        caixa.replaceChildren(estadoCaixa(nao ? "aviso" : "sucesso", nao ? "Aviso:" : "", texto));
        anunciar(texto);
        if (r.arquivos.some((a) => a.situacao === "ja_estava"))
          caixa.append(h("p", { text: "Esta foto já foi processada antes. Ela entra na execução e usa o resultado guardado." }));
      } catch (e) {
        caixa.replaceChildren(estadoCaixa("erro", "Erro:", e.message));
      }
      S.foco = "arquivos"; desenharLista(); atualizar();
    }
    function desenharLista() {
      const alvo = $("envio-lista");
      alvo.replaceChildren();
      if (!S.envio.arquivos.length) return;
      const situacao = (a) => {
        const ok = a.situacao !== "recusado";
        const texto = a.situacao === "recebido" ? "Recebido" : a.situacao === "ja_estava" ? "Já estava aqui: resultado guardado" : "Recusado: " + a.motivo;
        return h("span", { class: "vf-situacao", "data-tipo": ok ? "ok" : "erro" }, icone(ok ? "feito" : "erro", "vf-icone--p"), " " + texto);
      };
      alvo.append(tabela("Arquivos deste envio", ["Arquivo", "Tamanho", "Situação", "Ação"],
        S.envio.arquivos.map((a, i) => [a.nome, mb(a.tamanho), situacao(a),
          botao("Remover", () => remover(i), { icone: "remover", oculto: a.nome })]),
        "vf-cartoes"),
        h("p", { class: "vf-caminho" }, icone("pasta"), " ", h("span", { text: "As fotos ficam em: " + S.envio.pasta })));
    }
    async function remover(i) {
      const a = S.envio.arquivos[i];
      try { if (a.arquivo_id && S.envio.id) await api("DELETE", "/api/materiais/" + S.envio.id + "/" + a.arquivo_id); }
      catch (e) { $("envio-estado").replaceChildren(estadoCaixa("erro", "Erro:", e.message)); return; }
      S.envio.arquivos.splice(i, 1);
      if (!S.envio.arquivos.some((x) => x.arquivo_id)) S.envio = { id: null, arquivos: [], pasta: "" };
      render();
    }
    const rodape = h("div", { id: "envio-acoes" });
    painel.append(rodape);
    function atualizar() {
      const recebidos = S.envio.arquivos.filter((a) => a.situacao !== "recusado").length;
      const motivo = !REGEX_DISCIPLINA.test(S.disciplina) ? "Escolha a disciplina." : recebidos === 0 ? "Envie ao menos um arquivo." : null;
      rodape.replaceChildren(acoes("motivo-2", motivo,
        botao("Voltar", () => ir("processar", 1)),
        botao("Continuar", () => ir("processar", 3), { primario: true, desabilitado: !!motivo, motivoId: motivo ? "motivo-2" : null })));
    }
    desenharLista(); atualizar();
  }

  // ----------------------------------------------------------------- passo 3
  async function passo3(painel) {
    painel.append(titulo("Quanto custa e quanto demora"));
    if (!S.envio.id) { ir("processar", 2); return; }
    const alvo = h("div", {}, h("p", { class: "vf-estado vf-estado--carregando", role: "status", text: "Calculando…" }));
    painel.append(alvo);
    let e;
    try { e = await api("POST", "/api/estimativa", { envio_id: S.envio.id, etapas: [...S.etapas] }); }
    catch (erro) {
      alvo.replaceChildren(estadoCaixa("erro", "Erro:", "não consegui calcular a estimativa. " + erro.message),
        h("div", { class: "vf-acoes" }, botao("Tentar de novo", () => render(), { icone: "recarregar" }), botao("Voltar", () => ir("processar", 2))));
      return;
    }
    S.estimativa = e;
    const origem = { guardado: "Resultado guardado", historico: null, sem_historico: "Você ainda não rodou esta etapa" };
    const nomeMaterial = (MATERIAIS.find((m) => m[0] === S.material) || [])[1];
    const resumo = h("dl", { class: "vf-resumo" },
      [["Material", nomeMaterial], ["Disciplina", S.disciplina], ["Arquivos", String(S.envio.arquivos.filter((a) => a.situacao !== "recusado").length)],
       ["Etapas", e.etapas.map((x) => x.rotulo).join(", ")]].map(([k, v]) => h("div", {}, h("dt", { text: k }), h("dd", { text: v }))));
    const cab = ["Etapa", "Custo estimado", "Tempo de espera estimado", "De onde vem"];
    const linhas = e.etapas.map((x) => [x.rotulo, usd(x.custo_usd), segundos(x.espera_s),
      x.origem === "historico" ? "Mediana das suas últimas " + x.n + " execuções" : origem[x.origem]]);
    const semHistorico = e.etapas.every((x) => x.origem === "sem_historico");
    alvo.replaceChildren(resumo,
      h("p", { class: "vf-total" }, h("span", { class: "vf-total-rotulo", text: "Total estimado" }),
        h("strong", { class: "vf-total-valor", text: (e.total_incompleto ? "a partir de " : "") + usd(e.total_usd) })),
      tabela("Estimativa por etapa", cab, linhas, "vf-cartoes"));
    if (semHistorico) alvo.append(h("p", { text: "Ainda não há histórico neste computador para estimar. Depois da primeira execução, a estimativa passa a usar os seus próprios números." }));
    else if (e.total_incompleto) alvo.append(h("p", { text: "O total real pode ser maior. O limite de gasto do mês protege você." }));
    alvo.append(h("details", { class: "vf-detalhe" }, h("summary", { text: "Como ler estes números" }),
      h("p", { text: "Tempo de atenção é o tempo em que você precisa estar presente. Tempo de espera é o da máquina. Tempo de atenção: ainda não medido. Veja a aba Economia." }),
      e.etapas.some((x) => x.origem === "guardado") ? h("p", { text: "Resultado guardado é o que o class2md já calculou para este mesmo arquivo. Usar de novo não custa nada." }) : null),
      h("dl", { class: "vf-metricas" }, [["Gasto do mês", usd(e.gasto_mes_usd)], ["Limite do mês", usd(e.teto_usd)], ["Sobra", usd(e.sobra_usd)]]
        .map(([k, v]) => h("div", { class: "vf-metrica" }, h("dt", { text: k }), h("dd", { class: "vf-num", text: v })))));
    if (e.bloqueado === "limite_atingido")
      alvo.append(estadoCaixa("erro", "Bloqueado:", "o limite do mês foi atingido. O class2md não faz chamadas novas até o mês virar ou o limite mudar. Etapas com resultado guardado continuam funcionando."));
    else if (e.bloqueado)
      alvo.append(estadoCaixa("erro", "Bloqueado:", "a estimativa passa do limite do mês. Para continuar, tire etapas ou aumente TETO_MENSAL_USD no .env e reinicie."));

    const caixa = h("input", { type: "checkbox", id: "confirmo" });
    const rodar = h("button", { class: "vf-botao vf-botao--primario", type: "button", disabled: true, "aria-describedby": "motivo-3" }, "Confirmar e rodar");
    const motivo = h("p", { class: "vf-acoes-motivo", id: "motivo-3" });
    const atualizar = () => {
      const ok = !e.bloqueado && (e.tudo_guardado || caixa.checked);
      rodar.disabled = !ok;
      motivo.textContent = e.bloqueado ? "O limite do mês bloqueia esta execução." : ok ? "" : "Marque a confirmação para rodar.";
    };
    caixa.addEventListener("change", atualizar);
    rodar.addEventListener("click", async () => {
      rodar.disabled = true;
      try {
        const r = await api("POST", "/api/processar", { envio_id: S.envio.id, etapas: [...S.etapas], confirmado: true });
        S.jobId = r.job_id; guardar("jobId", r.job_id); ir("processar", 4);
      } catch (erro) { alvo.append(estadoCaixa("erro", "Erro:", erro.message)); atualizar(); }
    });
    alvo.append(h("div", { class: "vf-confirma" },
      e.tudo_guardado ? h("p", { text: "Tudo já está guardado. Rodar de novo não gera cobrança." }) : [caixa, h("label", { for: "confirmo", text: "Entendi que isto usa a minha chave e pode gerar cobrança." })],
      h("div", { class: "vf-acoes" }, botao("Voltar", () => ir("processar", 2)), rodar, motivo)));
    atualizar();
  }

  // ----------------------------------------------------------------- passo 4
  async function passo4(painel) {
    const cab = h("h2", { tabindex: "-1", "aria-live": "polite", text: "Rodando" });
    const corpo = h("div", {});
    painel.append(cab, corpo);
    const consultar = async () => {
      let d;
      try { d = await api("GET", "/api/jobs/" + S.jobId); }
      catch (e) { corpo.replaceChildren(estadoCaixa("erro", "Erro:", e.message)); return; }
      S.execucao = d;
      desenharAcompanhamento(cab, corpo, d);
      if (d.estado === "rodando") S.timer = setTimeout(consultar, document.hidden ? 5000 : 1000);
      else { await carregarEstado(); anunciar(cab.textContent); }
    };
    await consultar();
  }

  function desenharAcompanhamento(cab, corpo, d) {
    const titulos = { rodando: "Rodando", concluido: "Pronto", parcial: "Pronto", aguardando_humano: "Parou para uma pergunta", falhou: "Falhou", limite: "Parou" };
    cab.textContent = titulos[d.estado];
    const lista = h("ol", { class: "vf-progresso" }, d.etapas.map((e) => {
      const [, palavra] = SITUACAO_ETAPA[e.estado] || SITUACAO_ETAPA.espera;
      return h("li", { class: "vf-progresso-item", "data-estado": e.estado, "aria-current": e.estado === "rodando" ? "step" : null },
        h("span", { class: "vf-progresso-marca", "aria-hidden": "true" }, icone("e-" + e.estado)),
        h("span", { class: "vf-progresso-nome", text: e.rotulo }), h("span", { class: "vf-progresso-situacao", text: palavra }));
    }));
    const resumo = h("dl", { class: "vf-metricas" }, [["Custo até agora", usd(d.custo_usd)], ["Tempo decorrido", segundos(d.espera_s)],
      ["Resultados guardados usados", String(d.guardados)], ["Avisos", String(d.avisos.length)]].map(([k, v]) => h("div", { class: "vf-metrica" }, h("dt", { text: k }), h("dd", { class: "vf-num", text: v }))));
    const detalhe = h("details", { class: "vf-detalhe" }, h("summary", { text: "Ver cada agente" }),
      d.agentes.length ? tabela("Agentes desta execução", ["Agente", "Modelo", "Tokens", "Custo", "Resultado guardado", "Tempo"],
        d.agentes.map((a) => [a.agente, a.modelo || "sem dado", (a.tokens_in + a.tokens_out).toLocaleString("pt-BR"), usd(a.custo_usd), String(a.guardados), a.duracao_s === null ? "sem medida" : segundos(a.duracao_s)]), "vf-cartoes")
        : h("p", { text: "Nenhum agente rodou ainda." }));
    const primeiro = d.jobs[0];
    const final = [];
    if (d.estado === "concluido") {
      final.push(estadoCaixa("sucesso", "", "Pronto. A nota está na pasta de revisão."),
        h("div", { class: "vf-acoes" }, botao("Revisar a nota", () => { S.notaId = primeiro.id; ir("processar", 5); }, { primario: true })));
    } else if (d.estado === "parcial") {
      final.push(estadoCaixa("sucesso", "", "Pronto até aqui. Você pediu só parte das etapas. Dá para continuar depois sem pagar de novo pelo que foi feito."),
        h("div", { class: "vf-acoes" }, botao("Continuar com mais etapas", () => { ir("processar", 1); }, { primario: true })));
    } else if (d.estado === "aguardando_humano") {
      const pausado = d.jobs.find((j) => j.status === "aguardando_humano") || primeiro;
      final.push(h("p", { text: "O class2md parou para perguntar:" }), h("p", { class: "vf-nota", text: pausado.pergunta || "Sem texto de pergunta." }),
        h("div", { class: "vf-acoes" },
          botao("Continuar mesmo assim", async () => {
            if (await confirmar({ titulo: "Continuar mesmo assim?", texto: "A pergunta foi: " + (pausado.pergunta || "") + " Continuar faz o class2md processar estas fotos mesmo assim. Isso pode gerar cobrança." })) retomar(pausado.id);
          }, { primario: true }),
          botao("Deixar para depois", () => ir("notas"), { discreto: true })));
    } else if (d.estado === "falhou") {
      final.push(estadoCaixa("erro", "Erro:", "a execução falhou. O que já foi feito ficou guardado. " + (d.erro || "")),
        h("div", { class: "vf-acoes" }, botao("Tentar de novo", async () => {
          if (await confirmar({ titulo: "Tentar de novo?", texto: "O class2md reaproveita o resultado guardado. O que faltar pode gerar cobrança." })) {
            if (primeiro) retomar(primeiro.id); else ir("processar", 3);
          }
        }, { primario: true, icone: "recarregar" })));
    } else if (d.estado === "limite") {
      final.push(estadoCaixa("erro", "Parou:", "o limite do mês foi atingido durante a execução. O que foi feito ficou guardado."),
        h("div", { class: "vf-acoes" }, botao("Ver custos", () => ir("ajuda"), { discreto: true })));
    }
    corpo.replaceChildren(lista, ...final, resumo, ...d.avisos.map((a) => estadoCaixa("aviso", "Aviso:", a)), detalhe,
      d.estado === "rodando" ? h("p", { text: "Para parar agora, use Ctrl+C no terminal. O que já foi feito fica guardado." }) : null);
  }

  async function retomar(jobId) {
    try {
      const r = await api("POST", "/api/jobs/" + jobId + "/continuar", { confirmado: true });
      S.jobId = r.job_id; guardar("jobId", r.job_id); render();
    } catch (e) { $("painel-processar").append(estadoCaixa("erro", "Erro:", e.message)); }
  }

  // ----------------------------------------------------------------- passo 5
  async function passo5(painel) {
    painel.append(titulo("Revisar a nota"),
      h("p", { class: "vf-nota" }, icone("pasta"), h("span", { text: "Esta nota está na pasta de revisão. O class2md não escreve no seu cofre do Obsidian. Quem leva a nota para lá é você." })));
    let n;
    try { n = await api("GET", "/api/notas/" + S.notaId); }
    catch (e) { painel.append(estadoCaixa("erro", "Erro:", e.message)); return; }
    const colNota = h("div", {}, h("h3", { text: n.arquivo || "Sem nota ainda" }),
      n.texto === null ? h("p", { class: "vf-estado vf-estado--vazio", text: "Esta execução ainda não tem nota." })
        : h("pre", { class: "vf-nota-texto", tabindex: "0", role: "region", "aria-label": "Texto da nota", text: n.texto }));
    const fotos = [];
    for (let i = 1; i <= n.fotos; i++) fotos.push(i);
    const colFotos = h("div", { class: "vf-revisao-origem" }, h("h3", { text: "Fotos de origem" }), h("ul", { class: "vf-fotos" }, fotos.map((i) => {
      const alt = "Foto " + i + " de " + n.fotos + " desta aula";
      return h("li", { class: "vf-foto" }, h("img", { src: "/api/notas/" + S.notaId + "/fotos/" + i, alt, loading: "lazy" }),
        botao("Ampliar", () => ampliar(i, n.fotos), { icone: "ampliar", oculto: "a foto " + i }));
    })));
    painel.append(h("div", { class: "vf-revisao" }, colNota, colFotos));

    const avisos = [];
    if (n.avisos.precisa_revisao) avisos.push(["A conferência automática apontou problemas. Leia com atenção:", n.avisos.problemas_validacao]);
    if (n.avisos.possivel_injecao) avisos.push(["Uma das fotos tinha texto que parecia uma ordem para a IA. O class2md tratou como texto comum. Confira o trecho na nota.", []]);
    if (n.avisos.avisos_conceitos.length) avisos.push(["Páginas de conceito com pendência:", n.avisos.avisos_conceitos]);
    if (n.avisos.pergunta) avisos.push(["Aviso da execução:", [n.avisos.pergunta]]);
    if (avisos.length) painel.append(h("div", { class: "vf-lista-avisos" }, h("h3", { text: "Avisos da nota" }),
      avisos.map(([texto, itens]) => h("div", {}, h("p", {}, icone("aviso"), texto), itens.length ? h("ul", {}, itens.map((i) => h("li", { text: i }))) : null))));
    if (n.duvidas.length) painel.append(h("h3", { text: "Dúvidas levantadas" }), h("p", { text: "São pontos que a própria aula deixou em aberto." }), h("ul", {}, n.duvidas.map((d) => h("li", { text: d }))));
    const baixar = h("a", { class: "vf-botao vf-botao--primario", href: "/api/notas/" + S.notaId + "/baixar", download: "" }, icone("baixar"), " Baixar a nota (.md)");
    painel.append(h("div", { class: "vf-acoes" }, n.texto === null ? null : baixar,
      botao("Copiar o caminho da pasta de revisão", async () => { try { await navigator.clipboard.writeText(n.pasta_de_revisao); anunciar("Caminho copiado"); } catch (e) { anunciar("Não consegui copiar"); } }, { icone: "copiar" }),
      botao("Como levar para o Obsidian", () => { S.foco = "ajuda-obsidian"; ir("ajuda"); }),
      botao("Processar outro material", () => { S.material = null; S.etapas = new Set(); S.envio = { id: null, arquivos: [], pasta: "" }; S.jobId = null; guardar("jobId", ""); ir("processar", 1); }, { discreto: true })));
    painel.append(h("p", {}, "Os flashcards, se a etapa rodou, estão em ", h("code", { text: n.flashcards }), ". No Anki: Arquivo, Importar."));
    painel.append(h("div", { class: "vf-cartao vf-cartao--futuro" }, h("h3", { text: "Tirar dúvidas antes de gravar" }), h("span", { class: "vf-marca", text: "Em desenvolvimento" }),
      h("p", { text: "Aqui você vai poder perguntar ao modelo sobre uma foto ou sobre a nota, ler a resposta com a fonte, e decidir o que entra. Ainda não está disponível." })));
  }
  function ampliar(i, total) {
    const fechar = h("button", { class: "vf-botao", type: "button" }, icone("fechar", "vf-icone--p"), " Fechar");
    const dialogo = h("dialog", { class: "vf-dialogo vf-dialogo--foto", "aria-labelledby": "dlg-foto" },
      h("h2", { class: "vf-dialogo-titulo", id: "dlg-foto", text: "Foto " + i + " de " + total }),
      h("img", { src: "/api/notas/" + S.notaId + "/fotos/" + i, alt: "Foto " + i + " de " + total + " desta aula, ampliada" }), h("div", { class: "vf-acoes" }, fechar));
    const sair = () => { dialogo.close(); dialogo.remove(); };
    fechar.addEventListener("click", sair);
    dialogo.addEventListener("close", () => dialogo.remove());
    document.body.append(dialogo);
    dialogo.showModal();
    fechar.focus();
  }

  // ------------------------------------------------------------------- notas
  async function telaNotas(painel) {
    painel.append(h("h2", { tabindex: "-1", text: "Notas na pasta de revisão" }));
    const alvo = h("div", {}, h("p", { class: "vf-estado vf-estado--carregando", role: "status", text: "Carregando as notas…" }));
    painel.append(alvo);
    let r;
    try { r = await api("GET", "/api/notas"); }
    catch (e) { alvo.replaceChildren(estadoCaixa("erro", "Erro:", "não consegui ler a lista de notas.")); return; }
    if (!r.notas.length) { alvo.replaceChildren(h("div", { class: "vf-estado vf-estado--vazio" }, icone("marca", "vf-icone--gg"), h("p", { text: "Nenhuma nota ainda. Comece pela aba Processar." }))); return; }
    alvo.replaceChildren(tabela("Execuções", ["Disciplina", "Data da aula", "Situação", "Avisos", "Ação"], r.notas.map((n) => [
      n.disciplina || "sem dado", n.data || "sem data", SITUACAO_NOTA[n.status] || n.status, n.avisos ? String(n.avisos) : "nenhum",
      botao(n.status === "concluido" ? "Revisar" : "Ver", () => { S.notaId = n.id; ir("processar", 5); })]), "vf-cartoes"));
  }

  // ----------------------------------------------------------------- economia
  function telaEconomia(painel) {
    painel.append(h("h2", { tabindex: "-1", text: "Economia de tempo" }), h("span", { class: "vf-marca", text: "Em desenvolvimento" }),
      h("p", { text: "Este painel vai mostrar quanto tempo de atenção o class2md poupa, a partir de medidas feitas por você. Ele nunca mostra número estimado." }),
      h("h3", { text: "Como medir" }),
      h("ol", {}, [
        "Escolha de 3 a 5 aulas parecidas.",
        "Para cada uma, cronometre o jeito manual: transcrever, montar a nota, criar os flashcards.",
        "Para as mesmas aulas, cronometre o tempo em que você fica ativo usando o class2md: enviar, escolher, ler, aprovar.",
        "Anote em medicao_class2md.csv, com as colunas material, modo, unidades, atencao_s, maquina_s, observacao.",
      ].map((t) => h("li", { text: t }))));
  }

  // -------------------------------------------------------------------- ajuda
  function telaAjuda(painel) {
    painel.append(h("h2", { tabindex: "-1", text: "Ajuda" }),
      h("h3", { text: "Como funciona" }),
      h("img", { class: "vf-fluxo", src: "/estatico/fluxo-class2md.svg", alt: "Seis etapas em sequência: fotos ou PDF, leitura pela IA, nota e flashcards escritos por agentes, pasta de revisão, revisão feita por você, e por fim Obsidian e Anki." }),
      h("ol", {}, ["Você envia fotos ou PDF.", "A IA lê o material.", "Agentes escrevem a nota e os flashcards.", "O resultado fica na pasta de revisão.", "Você revisa e decide.", "Você leva a nota para o Obsidian e os cartões para o Anki."].map((t) => h("li", { text: t }))),
      h("h3", { text: "Onde ficam os arquivos" }),
      tabela("Pastas dentro da pasta de dados", ["O quê", "Onde"], [
        ["Pasta de entrada", "estudos/inbox/<Disciplina>/"], ["Pasta de revisão", "estudos/output/"],
        ["Flashcards", "estudos/flashcards/<Disciplina>/"], ["Registro de gastos", "estado.db e logs/"]], "vf-cartoes"),
      h("h3", { id: "ajuda-obsidian", tabindex: "-1", text: "Como levar a nota para o Obsidian" }),
      codigo("uv run python scripts/promover.py"),
      h("p", { text: "O promotor mostra o plano antes e só escreve quando você confirma." }),
      h("h3", { text: "Quanto custa e como limitar" }),
      h("p", { text: "O limite do mês vem de TETO_MENSAL_USD no .env. Para ver o que já gastou:" }),
      codigo("uv run python scripts/estudos.py custos"),
      h("h3", { text: "Segurança" }),
      h("ul", {}, [
        "Esta página só responde neste computador.",
        "A chave da API fica no .env e nunca chega ao navegador.",
        "O class2md não escreve no seu cofre do Obsidian.",
        "Texto que vem de foto ou PDF é tratado como dado, nunca como ordem.",
      ].map((t) => h("li", { text: t }))),
      h("h3", { text: "Linha de comando equivalente" }),
      tabela("Ação da tela e comando", ["Ação da tela", "Comando"], [
        ["Processar fotos", "uv run python scripts/estudos.py processar"],
        ["Só algumas etapas", "uv run python scripts/estudos.py processar --etapas leitura"],
        ["Refazer sem gastar de novo", "uv run python scripts/estudos.py reprocessar <execução> --com-cache"],
        ["Ver gastos", "uv run python scripts/estudos.py custos"]], "vf-cartoes"));
  }

  // --------------------------------------------------------------------- início
  async function iniciar() {
    montarAbas();
    window.addEventListener("hashchange", render);
    try { await carregarEstado(); }
    catch (e) { $("painel-processar").append(estadoCaixa("erro", "Erro:", e.message)); return; }
    if (!location.hash && ler("jobId")) { S.jobId = ler("jobId"); location.hash = "#processar/4"; return; }
    render();
  }
  iniciar();
})();
