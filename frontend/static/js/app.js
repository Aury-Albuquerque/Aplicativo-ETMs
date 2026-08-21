// Compartilhado com o time (via GitHub) — lista real vem de /api/tags/opcoes,
// isso aqui é só um valor inicial pra não travar a interface antes do fetch.
const TAG_OPCOES_PADRAO = ["OS em campo", "Stand By", "Validação Final"];
const NOME_USUARIO_STORAGE_KEY = "etm_nome_usuario";
// Compartilhado com o time (via GitHub) — lista real vem de /api/diagnosticos/opcoes,
// isso aqui é só um valor inicial pra não travar a interface antes do fetch.
const DIAGNOSTICO_OPCOES_PADRAO = ["Falha de Equipamento", "Falha de Comunicação", "Sujidade", "Outro"];
// Idem, lista real vem de /api/status-pos-os/opcoes.
const STATUS_POS_OS_OPCOES_PADRAO = ["Chamado de Garantia", "Alinhamento com o Cliente", "Regularizado"];

const state = {
  usinas: [],
  usinasDoClienteAtual: [],
  usinaAtual: null,
  clienteAtual: null,
  plannerData: null,
  filtros: {
    cliente: "",
    usina: "",
    criadoPor: "",
    responsavel: "",
    tiposTrabalho: new Set(["analise", "campo"]),
    dataInicio: "",
    dataFim: "",
  },
  filtroDataHistorico: { inicio: "", fim: "" },
  tagsSelecionadas: new Set(),
  mostrarCanceladasPlanner: false,
  mostrarCanceladasHistorico: false,
  historicoAtual: [],
  modalFolioAtual: null,
  diagnosticoOpcoes: DIAGNOSTICO_OPCOES_PADRAO,
  statusPosOsOpcoes: STATUS_POS_OS_OPCOES_PADRAO,
  tagOpcoes: TAG_OPCOES_PADRAO,
  chatUsinaAberto: false,
  abertasFiltros: {
    cliente: "",
    criadoPor: "",
    tiposTrabalho: new Set(["analise", "campo"]),
    dataInicio: "",
    dataFim: "",
  },
  usinaAbertaAtual: null,
};

// ---------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------
function formatarData(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function formatarDataHora(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const data = d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  const hora = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return `${data} ${hora}`;
}

// Filtro de período: uma OS "estava ativa" entre dataInicioStr e dataFimStr
// se ela já existia até o fim do período (criada até dataFim) e ainda não
// tinha sido encerrada antes do início do período (encerrada antes de
// dataInicio some da lista). OS ainda aberta (não finalizada/cancelada) não
// tem "fim", então continua valendo enquanto já tiver sido criada a tempo.
function osAtivaNoPeriodo(os, dataInicioStr, dataFimStr) {
  if (!dataInicioStr && !dataFimStr) return true;
  const inicioOs = os.data_criacao ? new Date(os.data_criacao) : null;
  if (!inicioOs || Number.isNaN(inicioOs.getTime())) return true;

  const encerrada = os.status_bucket === "finalizada" || os.status_bucket === "cancelada";
  const fimOsBruto = encerrada ? os.data_final || os.data_criacao : null;
  const fimOs = fimOsBruto ? new Date(fimOsBruto) : null;

  if (dataFimStr) {
    const fimFiltro = new Date(`${dataFimStr}T23:59:59`);
    if (inicioOs > fimFiltro) return false;
  }
  if (dataInicioStr) {
    const inicioFiltro = new Date(`${dataInicioStr}T00:00:00`);
    if (fimOs && fimOs < inicioFiltro) return false;
  }
  return true;
}

function escapeHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}

const BADGE_LABEL = {
  nao_iniciada: "Não iniciada",
  em_andamento: "Em andamento",
  finalizada: "Finalizada",
  cancelada: "Cancelada",
};

function badgeHtml(bucket) {
  return `<span class="badge badge-${bucket}">${BADGE_LABEL[bucket] || bucket}</span>`;
}

async function fetchJson(url, options) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `Erro ${resp.status}`);
  }
  return resp.json();
}

// ---------------------------------------------------------------------
// Nome do usuário (guardado neste PC, usado como autor dos comentários)
// ---------------------------------------------------------------------
function getNomeUsuario() {
  return (localStorage.getItem(NOME_USUARIO_STORAGE_KEY) || "").trim();
}

function initNomeUsuario() {
  const input = document.getElementById("nome-usuario-input");
  input.value = getNomeUsuario();
  input.addEventListener("input", () => {
    localStorage.setItem(NOME_USUARIO_STORAGE_KEY, input.value.trim());
    atualizarEstadoInputComentario();
  });
}

// ---------------------------------------------------------------------
// Etiquetas (compartilhadas com todo o time, via GitHub — igual diagnóstico)
// ---------------------------------------------------------------------
async function alternarTagDaOs(os, tag) {
  const resp = await fetchJson(`/api/os/${encodeURIComponent(os.folio)}/tags/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tag }),
  });
  os.etiquetas = resp.etiquetas;
  return resp.etiquetas;
}

// ---------------------------------------------------------------------
// Abas
// ---------------------------------------------------------------------
function initTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    });
  });
}

// ---------------------------------------------------------------------
// Colunas retráteis
// ---------------------------------------------------------------------
function initColunasRetrateis() {
  document.querySelectorAll(".collapse-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.dataset.target;
      const targetEl = document.getElementById(targetId);
      const colapsada = targetEl.classList.toggle("collapsed");
      btn.classList.toggle("collapsed", colapsada);
      btn.setAttribute("aria-expanded", String(!colapsada));
      btn.textContent = colapsada ? "▸" : "▾";

      // A linha de filtro de etiquetas fica junto da coluna "Em andamento"
      if (targetId === "col-em-andamento") {
        document.getElementById("tag-filtro-row").classList.toggle("hidden", colapsada);
      }
    });
  });
}

// ---------------------------------------------------------------------
// Planner — cards
// ---------------------------------------------------------------------
function renderTagsDoCard(os) {
  const tagsFracttal = os.etiquetas_fracttal || [];
  const tagsLocais = os.etiquetas || [];
  const badgesFracttal = tagsFracttal
    .map((t) => `<span class="card-tag-badge card-tag-badge-fracttal" title="Etiqueta do Fracttal">${t}</span>`)
    .join("");
  const badgesLocais = tagsLocais.map((t) => `<span class="card-tag-badge">${t}</span>`).join("");
  return `
    <div class="card-tags" data-folio="${os.folio}">
      ${badgesFracttal}
      ${badgesLocais}
      <button type="button" class="card-tag-add-btn" data-folio="${os.folio}">+ etiqueta</button>
    </div>
  `;
}

const STATUS_FRACTTAL_CLASS = {
  "Não iniciada": "badge-fracttal-nao-iniciada",
  "Em progresso": "badge-fracttal-progresso",
  "Pausada": "badge-fracttal-pausada",
  "Finalizada": "badge-fracttal-finalizada",
};

function statusFracttalBadgeHtml(os) {
  if (!os.status_fracttal) return "";
  const classe = STATUS_FRACTTAL_CLASS[os.status_fracttal] || "";
  return `<span class="badge badge-fracttal ${classe}" title="Status da tarefa no Fracttal">${os.status_fracttal}</span>`;
}

function diagnosticoBadgeHtml(os) {
  return os.diagnostico ? `<span class="badge badge-diagnostico">${os.diagnostico}</span>` : "";
}

function diagnosticoBotaoHtml(os) {
  return `<button type="button" class="diagnostico-btn" data-folio="${os.folio}" title="Definir diagnóstico">${os.diagnostico ? "✎" : "+ diagnóstico"}</button>`;
}

function statusPosOsBadgeHtml(os) {
  return os.status_pos_os ? `<span class="badge badge-status-pos-os">${os.status_pos_os}</span>` : "";
}

function statusPosOsBotaoHtml(os) {
  return `<button type="button" class="status-pos-os-btn" data-folio="${os.folio}" title="Definir status pós-OS">${os.status_pos_os ? "✎" : "+ status pós-OS"}</button>`;
}

function acompanhamentoBadgeHtml(os) {
  return os.em_acompanhamento ? `<span class="badge badge-acompanhamento">Em Acompanhamento</span>` : "";
}

function acompanhamentoBotaoHtml(os) {
  return `<button type="button" class="acompanhamento-btn ${os.em_acompanhamento ? "ativo" : ""}" data-folio="${os.folio}" title="Marcar/desmarcar como em acompanhamento">${os.em_acompanhamento ? "★ Em acompanhamento" : "☆ Acompanhar"}</button>`;
}

async function alternarAcompanhamento(os, btnEl) {
  const novoValor = !os.em_acompanhamento;
  if (btnEl) btnEl.disabled = true;
  try {
    await fetchJson(`/api/os/${encodeURIComponent(os.folio)}/acompanhamento`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ativo: novoValor }),
    });
    os.em_acompanhamento = novoValor;
    aplicarFiltrosERenderizar();
    if (state.usinaAbertaAtual) renderUsinaAbertaBoard();
    renderEstacoesAcompanhamento();
    if (state.modalFolioAtual === os.folio) abrirModal(os);
  } catch (err) {
    if (btnEl) btnEl.disabled = false;
    alert(`Não foi possível salvar: ${err.message}`);
  }
}

function renderCard(os, { comEtiquetas = false } = {}) {
  const div = document.createElement("div");
  div.className = "os-card";
  div.innerHTML = `
    <div class="folio">OS ${os.folio ?? "—"} ${os.em_analise ? '<span class="badge badge-analise">Análise de Engenharia</span>' : ""} ${statusFracttalBadgeHtml(os)} ${diagnosticoBadgeHtml(os)} ${statusPosOsBadgeHtml(os)} ${acompanhamentoBadgeHtml(os)}</div>
    <div class="titulo">${os.titulo || "(sem título)"}</div>
    <div class="meta">
      <span>${os.usina}</span>
      <span>${formatarData(os.data_criacao)}</span>
    </div>
    <div class="diagnostico-row">${diagnosticoBotaoHtml(os)} ${statusPosOsBotaoHtml(os)} ${acompanhamentoBotaoHtml(os)}</div>
    ${comEtiquetas ? renderTagsDoCard(os) : ""}
  `;
  div.addEventListener("click", (e) => {
    if (e.target.closest(".card-tag-add-btn")) {
      e.stopPropagation();
      abrirTagPopover(e.target, os);
      return;
    }
    if (e.target.closest(".diagnostico-btn")) {
      e.stopPropagation();
      abrirDiagnosticoPopover(e.target, os);
      return;
    }
    if (e.target.closest(".status-pos-os-btn")) {
      e.stopPropagation();
      abrirStatusPosOsPopover(e.target, os);
      return;
    }
    if (e.target.closest(".acompanhamento-btn")) {
      e.stopPropagation();
      alternarAcompanhamento(os, e.target.closest(".acompanhamento-btn"));
      return;
    }
    abrirModal(os);
  });
  return div;
}

function renderColumn(elId, countElId, lista, opcoes = {}) {
  const col = document.getElementById(elId);
  const countEl = document.getElementById(countElId);
  col.innerHTML = "";
  countEl.textContent = `(${lista.length})`;
  if (lista.length === 0) {
    col.innerHTML = `<div class="empty-msg">Nenhuma OS aqui</div>`;
    return;
  }
  lista.forEach((os) => col.appendChild(renderCard(os, opcoes)));
}

// ---------------------------------------------------------------------
// Popover de etiquetas
// ---------------------------------------------------------------------
function fecharTagPopover() {
  const existente = document.querySelector(".tag-popover");
  if (existente) existente.remove();
  document.removeEventListener("click", fecharTagPopoverSeClicouFora, true);
}

function fecharTagPopoverSeClicouFora(e) {
  const popover = document.querySelector(".tag-popover");
  if (popover && !popover.contains(e.target) && !e.target.classList.contains("card-tag-add-btn")) {
    fecharTagPopover();
  }
}

function abrirTagPopover(anchorEl, os) {
  fecharTagPopover();
  const rect = anchorEl.getBoundingClientRect();
  const popover = document.createElement("div");
  popover.className = "tag-popover";
  popover.style.top = `${rect.bottom + 6}px`;
  popover.style.left = `${Math.min(rect.left, window.innerWidth - 190)}px`;

  const tagsAtuais = new Set(os.etiquetas || []);
  popover.innerHTML = state.tagOpcoes
    .map(
      (tag) => `
      <label class="tag-popover-option">
        <input type="checkbox" value="${tag}" ${tagsAtuais.has(tag) ? "checked" : ""} />
        ${tag}
      </label>
    `
    )
    .join("");

  popover.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", async () => {
      cb.disabled = true;
      try {
        await alternarTagDaOs(os, cb.value);
        aplicarFiltrosERenderizar();
        // Reabre o popover atualizado no mesmo card (o DOM foi recriado)
        const novoBtn = document.querySelector(`.card-tag-add-btn[data-folio="${os.folio}"]`);
        if (novoBtn) abrirTagPopover(novoBtn, os);
      } catch (err) {
        cb.disabled = false;
        cb.checked = !cb.checked;
        alert(`Não foi possível salvar a etiqueta: ${err.message}`);
      }
    });
  });

  document.body.appendChild(popover);
  setTimeout(() => document.addEventListener("click", fecharTagPopoverSeClicouFora, true), 0);
}

// ---------------------------------------------------------------------
// Diagnóstico (etiqueta única por OS, compartilhada com o time via GitHub)
// ---------------------------------------------------------------------
function fecharDiagnosticoPopover() {
  const existente = document.querySelector(".diagnostico-popover");
  if (existente) existente.remove();
  document.removeEventListener("click", fecharDiagnosticoPopoverSeClicouFora, true);
}

function fecharDiagnosticoPopoverSeClicouFora(e) {
  const popover = document.querySelector(".diagnostico-popover");
  if (popover && !popover.contains(e.target) && !e.target.classList.contains("diagnostico-btn")) {
    fecharDiagnosticoPopover();
  }
}

function abrirDiagnosticoPopover(anchorEl, os) {
  fecharDiagnosticoPopover();
  const rect = anchorEl.getBoundingClientRect();
  const popover = document.createElement("div");
  popover.className = "tag-popover diagnostico-popover";
  popover.style.top = `${rect.bottom + 6}px`;
  popover.style.left = `${Math.min(rect.left, window.innerWidth - 220)}px`;

  const opcoesHtml = state.diagnosticoOpcoes
    .map(
      (op) => `
      <label class="tag-popover-option">
        <input type="radio" name="diagnostico-radio" value="${op}" ${os.diagnostico === op ? "checked" : ""} />
        ${op}
      </label>
    `
    )
    .join("");
  popover.innerHTML = `${opcoesHtml}<button type="button" class="diagnostico-limpar-btn">Remover diagnóstico</button>`;

  popover.querySelectorAll("input[type=radio]").forEach((radio) => {
    radio.addEventListener("change", () => salvarDiagnostico(os, radio.value));
  });
  popover.querySelector(".diagnostico-limpar-btn").addEventListener("click", () => salvarDiagnostico(os, null));

  document.body.appendChild(popover);
  setTimeout(() => document.addEventListener("click", fecharDiagnosticoPopoverSeClicouFora, true), 0);
}

async function salvarDiagnostico(os, diagnostico) {
  try {
    await fetchJson(`/api/os/${encodeURIComponent(os.folio)}/diagnostico`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ diagnostico }),
    });
    os.diagnostico = diagnostico;
    fecharDiagnosticoPopover();
    aplicarFiltrosERenderizar();
    if (state.modalFolioAtual === os.folio) abrirModal(os);
  } catch (err) {
    alert(`Não foi possível salvar o diagnóstico: ${err.message}`);
  }
}

// ---------------------------------------------------------------------
// Status pós-OS (etiqueta única por OS, compartilhada com o time via GitHub)
// ---------------------------------------------------------------------
function fecharStatusPosOsPopover() {
  const existente = document.querySelector(".status-pos-os-popover");
  if (existente) existente.remove();
  document.removeEventListener("click", fecharStatusPosOsPopoverSeClicouFora, true);
}

function fecharStatusPosOsPopoverSeClicouFora(e) {
  const popover = document.querySelector(".status-pos-os-popover");
  if (popover && !popover.contains(e.target) && !e.target.classList.contains("status-pos-os-btn")) {
    fecharStatusPosOsPopover();
  }
}

function abrirStatusPosOsPopover(anchorEl, os) {
  fecharStatusPosOsPopover();
  const rect = anchorEl.getBoundingClientRect();
  const popover = document.createElement("div");
  popover.className = "tag-popover status-pos-os-popover";
  popover.style.top = `${rect.bottom + 6}px`;
  popover.style.left = `${Math.min(rect.left, window.innerWidth - 220)}px`;

  const opcoesHtml = state.statusPosOsOpcoes
    .map(
      (op) => `
      <label class="tag-popover-option">
        <input type="radio" name="status-pos-os-radio" value="${op}" ${os.status_pos_os === op ? "checked" : ""} />
        ${op}
      </label>
    `
    )
    .join("");
  popover.innerHTML = `${opcoesHtml}<button type="button" class="diagnostico-limpar-btn">Remover status pós-OS</button>`;

  popover.querySelectorAll("input[type=radio]").forEach((radio) => {
    radio.addEventListener("change", () => salvarStatusPosOs(os, radio.value));
  });
  popover.querySelector(".diagnostico-limpar-btn").addEventListener("click", () => salvarStatusPosOs(os, null));

  document.body.appendChild(popover);
  setTimeout(() => document.addEventListener("click", fecharStatusPosOsPopoverSeClicouFora, true), 0);
}

async function salvarStatusPosOs(os, statusPosOs) {
  try {
    await fetchJson(`/api/os/${encodeURIComponent(os.folio)}/status-pos-os`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status_pos_os: statusPosOs }),
    });
    os.status_pos_os = statusPosOs;
    fecharStatusPosOsPopover();
    aplicarFiltrosERenderizar();
    if (state.modalFolioAtual === os.folio) abrirModal(os);
  } catch (err) {
    alert(`Não foi possível salvar o status pós-OS: ${err.message}`);
  }
}

// ---------------------------------------------------------------------
// Filtro por etiqueta (só na coluna Em andamento)
// ---------------------------------------------------------------------
function renderTagFiltroRow() {
  const row = document.getElementById("tag-filtro-row");
  row.innerHTML = state.tagOpcoes
    .map((tag) => `<button type="button" class="tag-chip" data-tag="${tag}">${tag}</button>`)
    .join("");
  row.querySelectorAll(".tag-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const tag = chip.dataset.tag;
      if (state.tagsSelecionadas.has(tag)) {
        state.tagsSelecionadas.delete(tag);
      } else {
        state.tagsSelecionadas.add(tag);
      }
      chip.classList.toggle("selected");
      aplicarFiltrosERenderizar();
    });
  });
}

// ---------------------------------------------------------------------
// Filtros (cliente / usina / criado por)
// ---------------------------------------------------------------------
function passaFiltrosGerais(os) {
  const f = state.filtros;
  if (f.cliente && os.cliente !== f.cliente) return false;
  if (f.usina && !os.usina.toLowerCase().includes(f.usina.toLowerCase())) return false;
  if (f.criadoPor && (os.criado_por || "").trim() !== f.criadoPor) return false;
  if (f.responsavel && (os.tecnico || "").trim() !== f.responsavel) return false;
  const tipoAtual = os.em_analise ? "analise" : "campo";
  if (!f.tiposTrabalho.has(tipoAtual)) return false;
  if (!osAtivaNoPeriodo(os, f.dataInicio, f.dataFim)) return false;
  return true;
}

function passaFiltroTags(os) {
  if (state.tagsSelecionadas.size === 0) return true;
  const tagsDaOs = new Set(os.etiquetas || []);
  for (const t of state.tagsSelecionadas) {
    if (tagsDaOs.has(t)) return true;
  }
  return false;
}

function popularFiltroCliente(todasAsOs) {
  const select = document.getElementById("filtro-cliente");
  const valorAtual = select.value;
  const clientes = Array.from(new Set(todasAsOs.map((o) => o.cliente).filter(Boolean))).sort();
  select.innerHTML =
    `<option value="">Todos</option>` +
    clientes.map((c) => `<option value="${c}">${c}</option>`).join("");
  select.value = clientes.includes(valorAtual) ? valorAtual : "";
}

// Extrai nomes únicos (sem espaço sobrando, o Fracttal às vezes traz assim)
// de um campo de uma lista de OS, pra popular os comboboxes de pessoa.
function extrairNomesUnicos(listaDeOs, campo) {
  return Array.from(
    new Set(listaDeOs.map((o) => (o[campo] || "").trim()).filter(Boolean))
  ).sort((a, b) => a.localeCompare(b, "pt-BR"));
}

// Liga um combobox pesquisável (input + dropdown) genérico. `getOpcoes`
// retorna a lista atual de nomes disponíveis; `onSelect` recebe o nome
// escolhido. Usado tanto pra "Criado por" quanto "Responsável".
function initCombobox({ wrapperId, inputId, dropdownId, getOpcoes, onSelect, onClear }) {
  const input = document.getElementById(inputId);
  const dropdown = document.getElementById(dropdownId);

  function render(filtroTexto) {
    const nomes = getOpcoes().filter((n) =>
      n.toLowerCase().includes((filtroTexto || "").toLowerCase())
    );
    dropdown.innerHTML =
      nomes.length === 0
        ? `<div class="combobox-empty">Nenhum nome encontrado</div>`
        : nomes.map((n) => `<div class="combobox-option" data-nome="${n}">${n}</div>`).join("");
    dropdown.querySelectorAll(".combobox-option").forEach((opt) => {
      opt.addEventListener("click", () => {
        input.value = opt.dataset.nome;
        dropdown.classList.add("hidden");
        onSelect(opt.dataset.nome);
      });
    });
  }

  input.addEventListener("focus", () => {
    render(input.value);
    dropdown.classList.remove("hidden");
  });
  input.addEventListener("input", () => {
    if (input.value.trim() === "") onClear();
    render(input.value);
    dropdown.classList.remove("hidden");
  });
  document.addEventListener("click", (e) => {
    const wrapper = document.getElementById(wrapperId);
    if (!wrapper.contains(e.target)) dropdown.classList.add("hidden");
  });
}

function initFiltros() {
  const selectCliente = document.getElementById("filtro-cliente");
  selectCliente.addEventListener("change", () => {
    state.filtros.cliente = selectCliente.value;
    aplicarFiltrosERenderizar();
  });

  const inputUsina = document.getElementById("filtro-usina");
  inputUsina.addEventListener("input", () => {
    state.filtros.usina = inputUsina.value.trim();
    aplicarFiltrosERenderizar();
  });

  initCombobox({
    wrapperId: "filtro-criador-wrapper",
    inputId: "filtro-criador-input",
    dropdownId: "filtro-criador-dropdown",
    getOpcoes: () => state.criadoresDisponiveis || [],
    onSelect: (nome) => {
      state.filtros.criadoPor = nome;
      aplicarFiltrosERenderizar();
    },
    onClear: () => {
      state.filtros.criadoPor = "";
      aplicarFiltrosERenderizar();
    },
  });

  initCombobox({
    wrapperId: "filtro-responsavel-wrapper",
    inputId: "filtro-responsavel-input",
    dropdownId: "filtro-responsavel-dropdown",
    getOpcoes: () => state.responsaveisDisponiveis || [],
    onSelect: (nome) => {
      state.filtros.responsavel = nome;
      aplicarFiltrosERenderizar();
    },
    onClear: () => {
      state.filtros.responsavel = "";
      aplicarFiltrosERenderizar();
    },
  });

  document.querySelectorAll("#tab-planner .filtro-chips-inline .tag-chip[data-tipo]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const tipo = chip.dataset.tipo;
      if (state.filtros.tiposTrabalho.has(tipo)) {
        // Não deixa desmarcar os dois ao mesmo tempo (senão nada aparece
        // e não fica óbvio o motivo) — pelo menos um sempre fica ativo.
        if (state.filtros.tiposTrabalho.size === 1) return;
        state.filtros.tiposTrabalho.delete(tipo);
      } else {
        state.filtros.tiposTrabalho.add(tipo);
      }
      chip.classList.toggle("selected");
      aplicarFiltrosERenderizar();
    });
  });

  document.getElementById("filtro-mostrar-canceladas-planner").addEventListener("change", (e) => {
    state.mostrarCanceladasPlanner = e.target.checked;
    aplicarFiltrosERenderizar();
  });

  const inputDataInicio = document.getElementById("filtro-data-inicio");
  const inputDataFim = document.getElementById("filtro-data-fim");
  inputDataInicio.addEventListener("change", () => {
    state.filtros.dataInicio = inputDataInicio.value;
    aplicarFiltrosERenderizar();
  });
  inputDataFim.addEventListener("change", () => {
    state.filtros.dataFim = inputDataFim.value;
    aplicarFiltrosERenderizar();
  });

  document.getElementById("filtro-limpar").addEventListener("click", () => {
    state.filtros = {
      cliente: "",
      usina: "",
      criadoPor: "",
      responsavel: "",
      tiposTrabalho: new Set(["analise", "campo"]),
      dataInicio: "",
      dataFim: "",
    };
    state.tagsSelecionadas.clear();
    selectCliente.value = "";
    inputUsina.value = "";
    document.getElementById("filtro-criador-input").value = "";
    document.getElementById("filtro-responsavel-input").value = "";
    inputDataInicio.value = "";
    inputDataFim.value = "";
    document.getElementById("tag-filtro-row").querySelectorAll(".tag-chip.selected").forEach((c) => c.classList.remove("selected"));
    document.querySelectorAll("#tab-planner .filtro-chips-inline .tag-chip").forEach((c) => c.classList.add("selected"));
    aplicarFiltrosERenderizar();
  });
}

function aplicarFiltrosERenderizar() {
  if (!state.plannerData) return;
  const data = state.plannerData;

  const naoIniciadas = data.nao_iniciadas.filter(passaFiltrosGerais);
  const emAndamento = data.em_andamento.filter(passaFiltrosGerais).filter(passaFiltroTags);
  const finalizadas = data.finalizadas.filter(passaFiltrosGerais);

  renderColumn("col-nao-iniciada", "count-nao-iniciada", naoIniciadas);
  renderColumn("col-em-andamento", "count-em-andamento", emAndamento, { comEtiquetas: true });
  renderColumn("col-finalizada", "count-finalizada", finalizadas);

  const colunaCanceladas = document.getElementById("coluna-canceladas");
  colunaCanceladas.classList.toggle("hidden", !state.mostrarCanceladasPlanner);
  if (state.mostrarCanceladasPlanner) {
    const canceladas = (data.canceladas || []).filter(passaFiltrosGerais);
    renderColumn("col-cancelada", "count-cancelada", canceladas);
  }
}

// ---------------------------------------------------------------------
// Planner — carregamento
// ---------------------------------------------------------------------
async function carregarPlanner(refresh = false) {
  const statusEl = document.getElementById("planner-status");
  statusEl.textContent = "Carregando dados do Fracttal...";
  statusEl.classList.remove("error");
  try {
    const data = await fetchJson(`/api/planner${refresh ? "?refresh=true" : ""}`);
    state.plannerData = data;

    const todasAsOs = [...data.nao_iniciadas, ...data.em_andamento, ...data.finalizadas];
    const osAtivas = [...data.nao_iniciadas, ...data.em_andamento];
    popularFiltroCliente(todasAsOs);
    state.criadoresDisponiveis = extrairNomesUnicos(osAtivas, "criado_por");
    state.responsaveisDisponiveis = extrairNomesUnicos(osAtivas, "tecnico");

    aplicarFiltrosERenderizar();
    statusEl.textContent = `${data.total} OS corretivas de ETM · atualizado agora`;

    popularFiltroClienteAbertas();
    renderUsinasAbertasGrid();
    if (state.usinaAbertaAtual) renderUsinaAbertaBoard();
  } catch (err) {
    statusEl.textContent = `Erro ao carregar: ${err.message}`;
    statusEl.classList.add("error");
  }
}

// ---------------------------------------------------------------------
// Estações em Aberto (resumo: usinas com pelo menos 1 OS não iniciada ou
// em andamento — filtráveis por cliente/criado por/tipo de trabalho)
// ---------------------------------------------------------------------
function passaFiltrosAbertas(os) {
  const f = state.abertasFiltros;
  if (f.cliente && os.cliente !== f.cliente) return false;
  if (f.criadoPor && (os.criado_por || "").trim() !== f.criadoPor) return false;
  const tipoAtual = os.em_analise ? "analise" : "campo";
  if (!f.tiposTrabalho.has(tipoAtual)) return false;
  if (!osAtivaNoPeriodo(os, f.dataInicio, f.dataFim)) return false;
  return true;
}

// "3 semanas em aberto" / "2 dias em aberto", a partir da OS mais antiga
// (por data de criação) ainda não iniciada/em andamento daquela usina.
function tempoEmAbertoTexto(dataMaisAntiga) {
  if (!dataMaisAntiga) return "";
  const dias = Math.floor((Date.now() - dataMaisAntiga.getTime()) / (1000 * 60 * 60 * 24));
  if (dias <= 0) return "hoje";
  if (dias < 7) return `${dias} dia${dias === 1 ? "" : "s"} em aberto`;
  const semanas = Math.floor(dias / 7);
  return `${semanas} semana${semanas === 1 ? "" : "s"} em aberto`;
}

function computeUsinasAbertas() {
  if (!state.plannerData) return [];
  const abertas = [...state.plannerData.nao_iniciadas, ...state.plannerData.em_andamento].filter(
    passaFiltrosAbertas
  );
  const porUsina = new Map();
  abertas.forEach((os) => {
    if (!porUsina.has(os.usina)) {
      porUsina.set(os.usina, { nome: os.usina, cliente: os.cliente, quantidade: 0, maisAntiga: null });
    }
    const info = porUsina.get(os.usina);
    info.quantidade += 1;
    const dt = os.data_criacao ? new Date(os.data_criacao) : null;
    if (dt && !Number.isNaN(dt.getTime()) && (!info.maisAntiga || dt < info.maisAntiga)) {
      info.maisAntiga = dt;
    }
  });
  return Array.from(porUsina.values()).sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
}

function renderUsinaAbertaCard(info) {
  const div = document.createElement("div");
  div.className = "usina-card";
  const tempo = tempoEmAbertoTexto(info.maisAntiga);
  div.innerHTML = `
    <h3>${info.nome}</h3>
    <p>${info.quantidade} OS em aberto ${tempo ? `<span class="tempo-aberto-badge">${tempo}</span>` : ""}</p>
  `;
  div.addEventListener("click", () => abrirUsinaAberta(info.nome));
  return div;
}

// ---------------------------------------------------------------------
// Estações em Acompanhamento (subseção, logo abaixo das Estações em
// Aberto): usinas com pelo menos 1 OS marcada manualmente como "Em
// Acompanhamento" (normalmente já finalizada no Fracttal, mas com alguma
// pendência — ex: garantia — que a gente ainda quer acompanhar por aqui).
// ---------------------------------------------------------------------
function computeUsinasAcompanhamento() {
  if (!state.plannerData) return [];
  const f = state.abertasFiltros;
  const todas = [
    ...state.plannerData.nao_iniciadas,
    ...state.plannerData.em_andamento,
    ...state.plannerData.finalizadas,
    ...(state.plannerData.canceladas || []),
  ];
  const emAcompanhamento = todas
    .filter((os) => os.em_acompanhamento)
    .filter(passaFiltrosAbertas);
  const porUsina = new Map();
  emAcompanhamento.forEach((os) => {
    if (!porUsina.has(os.usina)) {
      porUsina.set(os.usina, { nome: os.usina, cliente: os.cliente, quantidade: 0 });
    }
    porUsina.get(os.usina).quantidade += 1;
  });
  return Array.from(porUsina.values()).sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
}

function renderUsinaAcompanhamentoCard(info) {
  const div = document.createElement("div");
  div.className = "usina-card";
  div.innerHTML = `
    <h3>${info.nome}</h3>
    <p>${info.quantidade} OS em acompanhamento</p>
  `;
  div.addEventListener("click", () => abrirUsinaAberta(info.nome));
  return div;
}

function renderEstacoesAcompanhamento() {
  const grid = document.getElementById("eea-acompanhamento-grid");
  if (!grid) return;
  const usinas = computeUsinasAcompanhamento();
  grid.innerHTML = "";
  if (usinas.length === 0) {
    grid.innerHTML = `<div class="empty-msg">Nenhuma estação em acompanhamento</div>`;
  } else {
    usinas.forEach((info) => grid.appendChild(renderUsinaAcompanhamentoCard(info)));
  }
}

function renderUsinasAbertasGrid() {
  const grid = document.getElementById("eea-usinas-grid");
  const status = document.getElementById("eea-status");
  if (!grid) return;

  const usinas = computeUsinasAbertas();
  grid.innerHTML = "";
  if (usinas.length === 0) {
    grid.innerHTML = `<div class="empty-msg">Nenhuma estação com OS em aberto pros filtros escolhidos</div>`;
  } else {
    usinas.forEach((info) => grid.appendChild(renderUsinaAbertaCard(info)));
  }
  const totalOs = usinas.reduce((soma, u) => soma + u.quantidade, 0);
  status.textContent = `${usinas.length} estaç${usinas.length === 1 ? "ão" : "ões"} · ${totalOs} OS em aberto`;
  renderEstacoesAcompanhamento();
}

function popularFiltroClienteAbertas() {
  if (!state.plannerData) return;
  const select = document.getElementById("eea-filtro-cliente");
  if (!select) return;
  const valorAtual = select.value;
  const abertas = [...state.plannerData.nao_iniciadas, ...state.plannerData.em_andamento];
  const clientes = Array.from(new Set(abertas.map((o) => o.cliente).filter(Boolean))).sort();
  select.innerHTML =
    `<option value="">Todos</option>` + clientes.map((c) => `<option value="${c}">${c}</option>`).join("");
  select.value = clientes.includes(valorAtual) ? valorAtual : "";
}

function initFiltrosAbertas() {
  const selectCliente = document.getElementById("eea-filtro-cliente");
  selectCliente.addEventListener("change", () => {
    state.abertasFiltros.cliente = selectCliente.value;
    renderUsinasAbertasGrid();
  });

  initCombobox({
    wrapperId: "eea-filtro-criador-wrapper",
    inputId: "eea-filtro-criador-input",
    dropdownId: "eea-filtro-criador-dropdown",
    getOpcoes: () => state.criadoresDisponiveis || [],
    onSelect: (nome) => {
      state.abertasFiltros.criadoPor = nome;
      renderUsinasAbertasGrid();
    },
    onClear: () => {
      state.abertasFiltros.criadoPor = "";
      renderUsinasAbertasGrid();
    },
  });

  document.querySelectorAll('#tab-abertas .filtro-chips-inline .tag-chip[data-tipo-abertas]').forEach((chip) => {
    chip.addEventListener("click", () => {
      const tipo = chip.dataset.tipoAbertas;
      if (state.abertasFiltros.tiposTrabalho.has(tipo)) {
        if (state.abertasFiltros.tiposTrabalho.size === 1) return;
        state.abertasFiltros.tiposTrabalho.delete(tipo);
      } else {
        state.abertasFiltros.tiposTrabalho.add(tipo);
      }
      chip.classList.toggle("selected");
      renderUsinasAbertasGrid();
    });
  });

  const inputDataInicio = document.getElementById("eea-filtro-data-inicio");
  const inputDataFim = document.getElementById("eea-filtro-data-fim");
  inputDataInicio.addEventListener("change", () => {
    state.abertasFiltros.dataInicio = inputDataInicio.value;
    renderUsinasAbertasGrid();
    if (state.usinaAbertaAtual) renderUsinaAbertaBoard();
  });
  inputDataFim.addEventListener("change", () => {
    state.abertasFiltros.dataFim = inputDataFim.value;
    renderUsinasAbertasGrid();
    if (state.usinaAbertaAtual) renderUsinaAbertaBoard();
  });

  document.getElementById("eea-filtro-limpar").addEventListener("click", () => {
    state.abertasFiltros = {
      cliente: "",
      criadoPor: "",
      tiposTrabalho: new Set(["analise", "campo"]),
      dataInicio: "",
      dataFim: "",
    };
    selectCliente.value = "";
    document.getElementById("eea-filtro-criador-input").value = "";
    inputDataInicio.value = "";
    inputDataFim.value = "";
    document
      .querySelectorAll("#tab-abertas .filtro-chips-inline .tag-chip")
      .forEach((c) => c.classList.add("selected"));
    renderUsinasAbertasGrid();
    if (state.usinaAbertaAtual) renderUsinaAbertaBoard();
  });
}

function renderUsinaAbertaBoard() {
  if (!state.plannerData || !state.usinaAbertaAtual) return;
  const nome = state.usinaAbertaAtual;
  const f = state.abertasFiltros;
  const doUsina = (lista) =>
    (lista || []).filter((os) => os.usina === nome).filter((os) => osAtivaNoPeriodo(os, f.dataInicio, f.dataFim));
  renderColumn("eea-col-nao-iniciada", "eea-count-nao-iniciada", doUsina(state.plannerData.nao_iniciadas));
  renderColumn("eea-col-em-andamento", "eea-count-em-andamento", doUsina(state.plannerData.em_andamento), {
    comEtiquetas: true,
  });
  renderColumn("eea-col-finalizada", "eea-count-finalizada", doUsina(state.plannerData.finalizadas));
  renderColumn("eea-col-cancelada", "eea-count-cancelada", doUsina(state.plannerData.canceladas));
}

function abrirUsinaAberta(nomeUsina) {
  state.usinaAbertaAtual = nomeUsina;
  document.getElementById("eea-lista-view").classList.add("hidden");
  document.getElementById("eea-detalhe-view").classList.remove("hidden");
  document.getElementById("eea-usina-titulo").textContent = nomeUsina;
  renderUsinaAbertaBoard();
}

function voltarListaAbertas() {
  document.getElementById("eea-detalhe-view").classList.add("hidden");
  document.getElementById("eea-lista-view").classList.remove("hidden");
  state.usinaAbertaAtual = null;
}

function irParaHistoricoDaUsina(nomeUsina) {
  const usinaInfo = state.usinas.find((u) => u.nome === nomeUsina);
  const cliente = usinaInfo ? usinaInfo.cliente : null;
  document.querySelector('.tab-btn[data-tab="historico"]').click();
  if (cliente) abrirCliente(cliente);
  abrirHistoricoUsina(nomeUsina);
}

// ---------------------------------------------------------------------
// Histórico — clientes
// ---------------------------------------------------------------------
function renderClienteCard(cliente, quantidadeUsinas) {
  const div = document.createElement("div");
  div.className = "cliente-card";
  div.innerHTML = `
    <h3>${cliente}</h3>
    <p>${quantidadeUsinas} usina${quantidadeUsinas !== 1 ? "s" : ""}</p>
  `;
  div.addEventListener("click", () => abrirCliente(cliente));
  return div;
}

function renderClientesGrid() {
  const grid = document.getElementById("clientes-grid");
  grid.innerHTML = "";
  const porCliente = new Map();
  state.usinas.forEach((u) => {
    const cliente = u.cliente || "Não identificado";
    porCliente.set(cliente, (porCliente.get(cliente) || 0) + 1);
  });
  const clientesOrdenados = Array.from(porCliente.keys()).sort();
  clientesOrdenados.forEach((cliente) => {
    grid.appendChild(renderClienteCard(cliente, porCliente.get(cliente)));
  });
}

function renderUsinasGrid(filtroTexto = "") {
  const grid = document.getElementById("usinas-grid");
  grid.innerHTML = "";
  const termo = filtroTexto.trim().toLowerCase();
  const filtradas = termo
    ? state.usinasDoClienteAtual.filter((u) => u.nome.toLowerCase().includes(termo))
    : state.usinasDoClienteAtual;

  if (filtradas.length === 0) {
    grid.innerHTML = `<div class="empty-msg">Nenhuma usina encontrada</div>`;
    return;
  }
  filtradas.forEach((u) => grid.appendChild(renderUsinaCard(u)));
}

function abrirCliente(cliente) {
  state.clienteAtual = cliente;
  document.getElementById("historico-clientes-view").classList.add("hidden");
  document.getElementById("historico-lista-view").classList.remove("hidden");
  document.getElementById("cliente-titulo").textContent = cliente;

  const inputBusca = document.getElementById("filtro-usina-historico");
  inputBusca.value = "";

  state.usinasDoClienteAtual = state.usinas
    .filter((u) => (u.cliente || "Não identificado") === cliente)
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  renderUsinasGrid();
}

function voltarParaClientes() {
  document.getElementById("historico-lista-view").classList.add("hidden");
  document.getElementById("historico-clientes-view").classList.remove("hidden");
}

// ---------------------------------------------------------------------
// Histórico — usinas
// ---------------------------------------------------------------------
function renderUsinaCard(usina) {
  const div = document.createElement("div");
  div.className = "usina-card";
  div.innerHTML = `
    <h3>${usina.nome}</h3>
    <p>${usina.etms.length} ETM${usina.etms.length !== 1 ? "s" : ""}</p>
  `;
  div.addEventListener("click", () => abrirHistoricoUsina(usina.nome));
  return div;
}

async function carregarUsinas(refresh = false) {
  const statusEl = document.getElementById("historico-status");
  statusEl.textContent = "Carregando usinas...";
  statusEl.classList.remove("error");
  try {
    const usinas = await fetchJson(`/api/usinas${refresh ? "?refresh=true" : ""}`);
    state.usinas = usinas;
    renderClientesGrid();
    const totalClientes = new Set(usinas.map((u) => u.cliente || "Não identificado")).size;
    statusEl.textContent = `${totalClientes} clientes · ${usinas.length} usinas com ETM cadastrada`;
  } catch (err) {
    statusEl.textContent = `Erro ao carregar: ${err.message}`;
    statusEl.classList.add("error");
  }
}

function renderHistoryItem(os) {
  const div = document.createElement("div");
  div.className = "history-item";
  div.innerHTML = `
    <div class="folio">OS ${os.folio ?? "—"} ${badgeHtml(os.status_bucket)} ${os.em_analise ? '<span class="badge badge-analise">Análise de Engenharia</span>' : ""} ${statusFracttalBadgeHtml(os)} ${diagnosticoBadgeHtml(os)} ${statusPosOsBadgeHtml(os)} ${acompanhamentoBadgeHtml(os)}</div>
    <div class="titulo">${os.titulo || "(sem título)"}</div>
    <div class="meta">${os.etm_codigo || ""} · criada em ${formatarData(os.data_criacao)}</div>
  `;
  div.addEventListener("click", () => abrirModal(os));
  return div;
}

function renderHistoricoLista() {
  const lista = document.getElementById("usina-historico-lista");
  const semCanceladas = state.mostrarCanceladasHistorico
    ? state.historicoAtual
    : state.historicoAtual.filter((os) => os.status_bucket !== "cancelada");
  const { inicio, fim } = state.filtroDataHistorico;
  const visiveis = semCanceladas.filter((os) => osAtivaNoPeriodo(os, inicio, fim));

  lista.innerHTML = "";
  if (visiveis.length === 0) {
    lista.innerHTML = `<div class="empty-msg">Nenhuma OS corretiva encontrada para esta usina</div>`;
    return;
  }
  visiveis.forEach((os) => lista.appendChild(renderHistoryItem(os)));
}

async function abrirHistoricoUsina(nomeUsina) {
  state.usinaAtual = nomeUsina;
  fecharChatUsina();
  document.getElementById("historico-lista-view").classList.add("hidden");
  document.getElementById("historico-detalhe-view").classList.remove("hidden");
  document.getElementById("usina-titulo").textContent = nomeUsina;
  const lista = document.getElementById("usina-historico-lista");
  lista.innerHTML = `<div class="empty-msg">Carregando histórico...</div>`;

  try {
    state.historicoAtual = await fetchJson(`/api/usinas/${encodeURIComponent(nomeUsina)}/historico`);
    renderHistoricoLista();
  } catch (err) {
    lista.innerHTML = `<div class="empty-msg">Erro ao carregar histórico: ${err.message}</div>`;
  }
}

function voltarParaUsinas() {
  document.getElementById("historico-detalhe-view").classList.add("hidden");
  document.getElementById("historico-lista-view").classList.remove("hidden");
  fecharChatUsina();
}

// ---------------------------------------------------------------------
// Modal de detalhe da OS
// ---------------------------------------------------------------------
function abrirModal(os) {
  const modal = document.getElementById("os-modal");
  const content = document.getElementById("modal-content");
  content.innerHTML = `
    <div class="folio">OS ${os.folio ?? "—"} ${badgeHtml(os.status_bucket)} ${os.em_analise ? '<span class="badge badge-analise">Análise de Engenharia</span>' : ""} ${statusFracttalBadgeHtml(os)} ${diagnosticoBadgeHtml(os)} ${diagnosticoBotaoHtml(os)} ${statusPosOsBadgeHtml(os)} ${statusPosOsBotaoHtml(os)} ${acompanhamentoBadgeHtml(os)} ${acompanhamentoBotaoHtml(os)}</div>
    <h3>${os.titulo || "(sem título)"}</h3>
    <dl>
      <dt>Usina</dt><dd>${os.usina}</dd>
      <dt>Cliente</dt><dd>${os.cliente || "—"}</dd>
      <dt>Tipo (Fracttal)</dt><dd>${os.tipo_os || "—"}</dd>
      <dt>ETM</dt><dd>${os.etm_descricao || os.etm_codigo || "—"}</dd>
      <dt>Descrição / Nota</dt><dd>${os.nota || "Sem nota registrada"}</dd>
      <dt>Técnico responsável</dt><dd>${os.tecnico || "—"}</dd>
      <dt>Solicitante</dt><dd>${os.solicitante || "—"}</dd>
      <dt>Criado por</dt><dd>${os.criado_por || "—"}</dd>
      <dt>Etiquetas do Fracttal</dt><dd>${(os.etiquetas_fracttal || []).join(", ") || "—"}</dd>
      ${
        os.os_pai_id
          ? `<dt>OS Pai</dt><dd>${os.os_pai_folio ? `OS ${os.os_pai_folio}` : `OT interna #${os.os_pai_id} (não carregada nesta consulta)`}</dd>`
          : ""
      }
      ${
        os.os_filhas && os.os_filhas.length > 0
          ? `<dt>OS Filha${os.os_filhas.length > 1 ? "s" : ""}</dt><dd>${os.os_filhas.map((f) => `OS ${f}`).join(", ")}</dd>`
          : ""
      }
      <dt>Criada em</dt><dd>${formatarData(os.data_criacao)}</dd>
      <dt>Iniciada em</dt><dd>${formatarData(os.data_inicial)}</dd>
      <dt>Finalizada em</dt><dd>${formatarData(os.data_final)}</dd>
    </dl>
    ${os.url ? `<a class="fracttal-link" href="${os.url}" target="_blank" rel="noopener">Abrir no Fracttal ↗</a>` : ""}
  `;
  modal.classList.remove("hidden");

  const diagBtn = content.querySelector(".diagnostico-btn");
  if (diagBtn) {
    diagBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      abrirDiagnosticoPopover(diagBtn, os);
    });
  }
  const statusBtn = content.querySelector(".status-pos-os-btn");
  if (statusBtn) {
    statusBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      abrirStatusPosOsPopover(statusBtn, os);
    });
  }
  const acompanhamentoBtn = content.querySelector(".acompanhamento-btn");
  if (acompanhamentoBtn) {
    acompanhamentoBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      alternarAcompanhamento(os, acompanhamentoBtn);
    });
  }

  state.modalFolioAtual = os.folio;
  document.getElementById("comentario-texto").value = "";
  atualizarEstadoInputComentario();
  carregarComentarios(os.folio);
}

function fecharModal() {
  document.getElementById("os-modal").classList.add("hidden");
  state.modalFolioAtual = null;
}

// ---------------------------------------------------------------------
// Comentários (compartilhados com todo o time, via GitHub)
// ---------------------------------------------------------------------
function renderComentario(c) {
  const div = document.createElement("div");
  div.className = "comentario-item";
  div.innerHTML = `
    <div class="comentario-cabecalho">
      <span class="comentario-autor">${escapeHtml(c.autor)}</span>
      <span class="comentario-data">${formatarDataHora(c.data)}</span>
    </div>
    <div class="comentario-texto">${escapeHtml(c.texto)}</div>
  `;
  return div;
}

async function carregarComentarios(folio) {
  const lista = document.getElementById("comentarios-lista");
  lista.innerHTML = `<div class="empty-msg">Carregando comentários...</div>`;
  try {
    const comentarios = await fetchJson(`/api/os/${encodeURIComponent(folio)}/comentarios`);
    // Não deixa uma resposta atrasada de uma OS antiga sobrescrever a atual
    if (state.modalFolioAtual !== folio) return;
    lista.innerHTML = "";
    if (comentarios.length === 0) {
      lista.innerHTML = `<div class="empty-msg">Nenhum comentário ainda. Seja o primeiro!</div>`;
      return;
    }
    comentarios.forEach((c) => lista.appendChild(renderComentario(c)));
    lista.scrollTop = lista.scrollHeight;
  } catch (err) {
    lista.innerHTML = `<div class="empty-msg">Erro ao carregar comentários: ${err.message}</div>`;
  }
}

function atualizarEstadoInputComentario() {
  const temNome = !!getNomeUsuario();
  document.getElementById("comentario-aviso-nome").classList.toggle("hidden", temNome);
  document.getElementById("comentario-enviar-btn").disabled = !temNome;
  document.getElementById("comentario-texto").disabled = !temNome;
}

// ---------------------------------------------------------------------
// Chat consolidado da usina (todas as OS, painel deslizante no Histórico)
// ---------------------------------------------------------------------
function renderComentarioComOs(c) {
  const div = document.createElement("div");
  div.className = "comentario-item";
  div.innerHTML = `
    <span class="comentario-os-ref" data-folio="${c.folio}" title="${escapeHtml(c.titulo_os || "")}">OS ${c.folio}</span>
    <div class="comentario-cabecalho">
      <span class="comentario-autor">${escapeHtml(c.autor)}</span>
      <span class="comentario-data">${formatarDataHora(c.data)}</span>
    </div>
    <div class="comentario-texto">${escapeHtml(c.texto)}</div>
  `;
  div.querySelector(".comentario-os-ref").addEventListener("click", () => {
    const os = state.historicoAtual.find((o) => String(o.folio) === String(c.folio));
    if (os) abrirModal(os);
  });
  return div;
}

async function carregarChatUsina(nomeUsina) {
  const lista = document.getElementById("chat-usina-lista");
  const status = document.getElementById("chat-usina-status");
  document.getElementById("chat-usina-titulo").textContent = `Chat · ${nomeUsina}`;
  status.textContent = "Carregando comentários...";
  status.classList.remove("error");
  lista.innerHTML = "";
  try {
    const comentarios = await fetchJson(`/api/usinas/${encodeURIComponent(nomeUsina)}/chat`);
    if (state.usinaAtual !== nomeUsina) return;
    if (comentarios.length === 0) {
      status.textContent = "Nenhum comentário em nenhuma OS desta usina ainda.";
      return;
    }
    status.textContent = `${comentarios.length} comentário${comentarios.length !== 1 ? "s" : ""} nesta usina`;
    comentarios.forEach((c) => lista.appendChild(renderComentarioComOs(c)));
  } catch (err) {
    status.textContent = `Erro ao carregar chat: ${err.message}`;
    status.classList.add("error");
  }
}

function abrirChatUsina() {
  state.chatUsinaAberto = true;
  document.getElementById("chat-usina-overlay").classList.remove("hidden");
  document.getElementById("chat-usina-panel").classList.add("aberto");
  carregarChatUsina(state.usinaAtual);
}

function fecharChatUsina() {
  state.chatUsinaAberto = false;
  document.getElementById("chat-usina-overlay").classList.add("hidden");
  document.getElementById("chat-usina-panel").classList.remove("aberto");
}

async function enviarComentario() {
  const nome = getNomeUsuario();
  const textarea = document.getElementById("comentario-texto");
  const texto = textarea.value.trim();
  const folio = state.modalFolioAtual;

  if (!nome) {
    document.getElementById("nome-usuario-input").focus();
    return;
  }
  if (!texto || !folio) return;

  const btn = document.getElementById("comentario-enviar-btn");
  btn.disabled = true;
  try {
    const novoComentario = await fetchJson(`/api/os/${encodeURIComponent(folio)}/comentarios`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ autor: nome, texto }),
    });
    const lista = document.getElementById("comentarios-lista");
    const vazio = lista.querySelector(".empty-msg");
    if (vazio) vazio.remove();
    lista.appendChild(renderComentario(novoComentario));
    lista.scrollTop = lista.scrollHeight;
    textarea.value = "";
  } catch (err) {
    alert(`Não foi possível enviar o comentário: ${err.message}`);
  } finally {
    btn.disabled = !getNomeUsuario();
  }
}

// ---------------------------------------------------------------------
// Atualização
// ---------------------------------------------------------------------
async function checarAtualizacao() {
  const dispensada = sessionStorage.getItem("etm_update_dispensada");
  try {
    const info = await fetchJson("/api/update-check");
    const versaoEl = document.getElementById("app-version");
    if (versaoEl && info.current_version) versaoEl.textContent = `· v${info.current_version}`;

    if (!info.update_available || dispensada === info.latest_version) return;

    const banner = document.getElementById("update-banner");
    const texto = document.getElementById("update-banner-text");
    texto.textContent = `Nova versão disponível: v${info.latest_version} (você está na v${info.current_version})`;
    banner.dataset.latestVersion = info.latest_version;
    banner.classList.remove("hidden");
  } catch (err) {
    // Sem internet, GitHub fora do ar, etc. — falha silenciosamente, não
    // atrapalha o uso normal do app.
    console.warn("Checagem de atualização falhou:", err);
  }
}

async function aplicarAtualizacao() {
  const btn = document.getElementById("update-apply-btn");
  const texto = document.getElementById("update-banner-text");
  btn.disabled = true;
  btn.textContent = "Atualizando...";
  try {
    await fetchJson("/api/update/apply", { method: "POST" });
    // A partir daqui o app atual vai fechar sozinho. Mostramos aviso mas o
    // servidor local também vai parar de responder.
    texto.textContent = "Instalando a atualização — esta janela vai fechar em instantes. Abra o app novamente pra usar a nova versão.";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Atualizar agora";
    texto.textContent = `Falha ao atualizar: ${err.message}`;
  }
}

function dispensarAtualizacao() {
  const banner = document.getElementById("update-banner");
  const versao = banner.dataset.latestVersion;
  if (versao) sessionStorage.setItem("etm_update_dispensada", versao);
  banner.classList.add("hidden");
}

// ---------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------
function init() {
  initTabs();
  initNomeUsuario();
  initColunasRetrateis();
  initFiltros();
  initFiltrosAbertas();
  renderTagFiltroRow();
  carregarPlanner();
  carregarUsinas();
  fetchJson("/api/diagnosticos/opcoes")
    .then((opcoes) => {
      state.diagnosticoOpcoes = opcoes;
    })
    .catch(() => {
      /* mantém DIAGNOSTICO_OPCOES_PADRAO se a busca falhar */
    });
  fetchJson("/api/tags/opcoes")
    .then((opcoes) => {
      state.tagOpcoes = opcoes;
      renderTagFiltroRow();
    })
    .catch(() => {
      /* mantém TAG_OPCOES_PADRAO se a busca falhar */
    });
  fetchJson("/api/status-pos-os/opcoes")
    .then((opcoes) => {
      state.statusPosOsOpcoes = opcoes;
    })
    .catch(() => {
      /* mantém STATUS_POS_OS_OPCOES_PADRAO se a busca falhar */
    });

  document.getElementById("refresh-btn").addEventListener("click", async (e) => {
    e.target.disabled = true;
    await Promise.all([carregarPlanner(true), carregarUsinas(true)]);
    if (state.usinaAtual) {
      await abrirHistoricoUsina(state.usinaAtual);
    } else if (state.clienteAtual) {
      abrirCliente(state.clienteAtual);
    }
    e.target.disabled = false;
  });

  document.getElementById("voltar-clientes").addEventListener("click", voltarParaClientes);
  document.getElementById("voltar-usinas").addEventListener("click", voltarParaUsinas);
  document.getElementById("eea-voltar-btn").addEventListener("click", voltarListaAbertas);
  document.getElementById("eea-ver-historico-btn").addEventListener("click", () => {
    if (state.usinaAbertaAtual) irParaHistoricoDaUsina(state.usinaAbertaAtual);
  });
  document.getElementById("filtro-usina-historico").addEventListener("input", (e) => {
    renderUsinasGrid(e.target.value);
  });
  document.getElementById("filtro-mostrar-canceladas-historico").addEventListener("change", (e) => {
    state.mostrarCanceladasHistorico = e.target.checked;
    renderHistoricoLista();
  });
  document.getElementById("historico-filtro-data-inicio").addEventListener("change", (e) => {
    state.filtroDataHistorico.inicio = e.target.value;
    renderHistoricoLista();
  });
  document.getElementById("historico-filtro-data-fim").addEventListener("change", (e) => {
    state.filtroDataHistorico.fim = e.target.value;
    renderHistoricoLista();
  });
  document.getElementById("abrir-chat-usina-btn").addEventListener("click", abrirChatUsina);
  document.getElementById("fechar-chat-usina-btn").addEventListener("click", fecharChatUsina);
  document.getElementById("chat-usina-overlay").addEventListener("click", fecharChatUsina);
  document.getElementById("modal-close").addEventListener("click", fecharModal);
  document.querySelector(".modal-backdrop").addEventListener("click", fecharModal);
  document.getElementById("comentario-enviar-btn").addEventListener("click", enviarComentario);
  document.getElementById("comentario-texto").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      enviarComentario();
    }
  });

  document.getElementById("update-apply-btn").addEventListener("click", aplicarAtualizacao);
  document.getElementById("update-dismiss-btn").addEventListener("click", dispensarAtualizacao);
  checarAtualizacao();
}

document.addEventListener("DOMContentLoaded", init);
