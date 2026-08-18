const state = {
  usinas: [],
  usinaAtual: null,
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
// Planner
// ---------------------------------------------------------------------
function renderCard(os) {
  const div = document.createElement("div");
  div.className = "os-card";
  div.innerHTML = `
    <div class="folio">OS ${os.folio ?? "—"}</div>
    <div class="titulo">${os.titulo || "(sem título)"}</div>
    <div class="meta">
      <span>${os.usina}</span>
      <span>${formatarData(os.data_criacao)}</span>
    </div>
  `;
  div.addEventListener("click", () => abrirModal(os));
  return div;
}

function renderColumn(elId, countElId, lista) {
  const col = document.getElementById(elId);
  const countEl = document.getElementById(countElId);
  col.innerHTML = "";
  countEl.textContent = `(${lista.length})`;
  if (lista.length === 0) {
    col.innerHTML = `<div class="empty-msg">Nenhuma OS aqui</div>`;
    return;
  }
  lista.forEach((os) => col.appendChild(renderCard(os)));
}

async function carregarPlanner(refresh = false) {
  const statusEl = document.getElementById("planner-status");
  statusEl.textContent = "Carregando dados do Fracttal...";
  statusEl.classList.remove("error");
  try {
    const data = await fetchJson(`/api/planner${refresh ? "?refresh=true" : ""}`);
    renderColumn("col-nao-iniciada", "count-nao-iniciada", data.nao_iniciadas);
    renderColumn("col-em-andamento", "count-em-andamento", data.em_andamento);
    renderColumn("col-finalizada", "count-finalizada", data.finalizadas);
    statusEl.textContent = `${data.total} OS corretivas de ETM · atualizado agora`;
  } catch (err) {
    statusEl.textContent = `Erro ao carregar: ${err.message}`;
    statusEl.classList.add("error");
  }
}

// ---------------------------------------------------------------------
// Histórico
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
    const grid = document.getElementById("usinas-grid");
    grid.innerHTML = "";
    usinas.forEach((u) => grid.appendChild(renderUsinaCard(u)));
    statusEl.textContent = `${usinas.length} usinas com ETM cadastrada`;
  } catch (err) {
    statusEl.textContent = `Erro ao carregar: ${err.message}`;
    statusEl.classList.add("error");
  }
}

function renderHistoryItem(os) {
  const div = document.createElement("div");
  div.className = "history-item";
  div.innerHTML = `
    <div class="folio">OS ${os.folio ?? "—"} ${badgeHtml(os.status_bucket)}</div>
    <div class="titulo">${os.titulo || "(sem título)"}</div>
    <div class="meta">${os.etm_codigo || ""} · criada em ${formatarData(os.data_criacao)}</div>
  `;
  div.addEventListener("click", () => abrirModal(os));
  return div;
}

async function abrirHistoricoUsina(nomeUsina) {
  state.usinaAtual = nomeUsina;
  document.getElementById("historico-lista-view").classList.add("hidden");
  document.getElementById("historico-detalhe-view").classList.remove("hidden");
  document.getElementById("usina-titulo").textContent = nomeUsina;
  const lista = document.getElementById("usina-historico-lista");
  lista.innerHTML = `<div class="empty-msg">Carregando histórico...</div>`;

  try {
    const historico = await fetchJson(`/api/usinas/${encodeURIComponent(nomeUsina)}/historico`);
    lista.innerHTML = "";
    if (historico.length === 0) {
      lista.innerHTML = `<div class="empty-msg">Nenhuma OS corretiva encontrada para esta usina</div>`;
      return;
    }
    historico.forEach((os) => lista.appendChild(renderHistoryItem(os)));
  } catch (err) {
    lista.innerHTML = `<div class="empty-msg">Erro ao carregar histórico: ${err.message}</div>`;
  }
}

function voltarParaUsinas() {
  document.getElementById("historico-detalhe-view").classList.add("hidden");
  document.getElementById("historico-lista-view").classList.remove("hidden");
}

// ---------------------------------------------------------------------
// Modal de detalhe da OS
// ---------------------------------------------------------------------
function abrirModal(os) {
  const modal = document.getElementById("os-modal");
  const content = document.getElementById("modal-content");
  content.innerHTML = `
    <div class="folio">OS ${os.folio ?? "—"} ${badgeHtml(os.status_bucket)}</div>
    <h3>${os.titulo || "(sem título)"}</h3>
    <dl>
      <dt>Usina</dt><dd>${os.usina}</dd>
      <dt>ETM</dt><dd>${os.etm_descricao || os.etm_codigo || "—"}</dd>
      <dt>Descrição / Nota</dt><dd>${os.nota || "Sem nota registrada"}</dd>
      <dt>Técnico responsável</dt><dd>${os.tecnico || "—"}</dd>
      <dt>Solicitante</dt><dd>${os.solicitante || "—"}</dd>
      <dt>Criada em</dt><dd>${formatarData(os.data_criacao)}</dd>
      <dt>Iniciada em</dt><dd>${formatarData(os.data_inicial)}</dd>
      <dt>Finalizada em</dt><dd>${formatarData(os.data_final)}</dd>
    </dl>
    ${os.url ? `<a class="fracttal-link" href="${os.url}" target="_blank" rel="noopener">Abrir no Fracttal ↗</a>` : ""}
  `;
  modal.classList.remove("hidden");
}

function fecharModal() {
  document.getElementById("os-modal").classList.add("hidden");
}

// ---------------------------------------------------------------------
// Atualização
// ---------------------------------------------------------------------
async function checarAtualizacao() {
  const dispensada = sessionStorage.getItem("etm_update_dispensada");
  try {
    const info = await fetchJson("/api/update-check");
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
  carregarPlanner();
  carregarUsinas();

  document.getElementById("refresh-btn").addEventListener("click", async (e) => {
    e.target.disabled = true;
    await Promise.all([carregarPlanner(true), carregarUsinas(true)]);
    if (state.usinaAtual) {
      await abrirHistoricoUsina(state.usinaAtual);
    }
    e.target.disabled = false;
  });

  document.getElementById("voltar-usinas").addEventListener("click", voltarParaUsinas);
  document.getElementById("modal-close").addEventListener("click", fecharModal);
  document.querySelector(".modal-backdrop").addEventListener("click", fecharModal);

  document.getElementById("update-apply-btn").addEventListener("click", aplicarAtualizacao);
  document.getElementById("update-dismiss-btn").addEventListener("click", dispensarAtualizacao);
  checarAtualizacao();
}

document.addEventListener("DOMContentLoaded", init);
