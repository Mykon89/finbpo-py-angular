// Robô de extratos do FinBPO.
//   node finbpo-robo.mjs porto            -> baixa os extratos novos da Porto
//   node finbpo-robo.mjs todas            -> todas as seguradoras de config.json
//   node finbpo-robo.mjs porto --desde 2026-11-01
//
// Cada seguradora usa um perfil de navegador próprio (pasta perfis/), então o login, o "lembrar este
// dispositivo" e o token ficam salvos como num Chrome normal. Se a sessão expirar, a janela fica aberta
// esperando você entrar (e digitar o token); depois o robô continua sozinho.
// O FinBPO não guarda senha nenhuma: quem guarda é o navegador do perfil, no seu computador.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const aqui = path.dirname(fileURLToPath(import.meta.url));
const cfgArq = path.join(aqui, 'config.json');
if (!fs.existsSync(cfgArq)) {
  console.error('Crie o config.json (copie de config.exemplo.json) com a pasta monitorada do FinBPO.');
  process.exit(1);
}
const cfg = JSON.parse(fs.readFileSync(cfgArq, 'utf8'));
const args = process.argv.slice(2);
const alvo = (args[0] || 'todas').toLowerCase();
const idxDesde = args.indexOf('--desde');
const hoje = new Date();
const desde = idxDesde >= 0 ? new Date(args[idxDesde + 1] + 'T00:00:00') : new Date(hoje.getFullYear(), hoje.getMonth() - 1, 1);
const registro = path.join(aqui, 'perfis', 'baixados.json');

function lerRegistro() {
  try { return JSON.parse(fs.readFileSync(registro, 'utf8')); } catch { return {}; }
}
function dd(d) {
  return `${String(d.getDate()).padStart(2, '0')}-${String(d.getMonth() + 1).padStart(2, '0')}-${d.getFullYear()}`;
}

async function rodar(seg) {
  const arqPortal = path.join(aqui, 'portais', `${seg}.mjs`);
  if (!fs.existsSync(arqPortal)) {
    console.log(`[${seg}] ainda não tem robô (portais/${seg}.mjs). Grave o caminho com "npm run gravar" e me envie.`);
    return;
  }
  const portal = await import(pathToFileURL(arqPortal).href);
  const perfil = path.join(aqui, 'perfis', seg);
  const ctx = await chromium.launchPersistentContext(perfil, { headless: false, acceptDownloads: true, viewport: null });
  const page = ctx.pages()[0] || (await ctx.newPage());
  const reg = lerRegistro();
  reg[seg] = reg[seg] || [];
  let baixados = 0;
  try {
    await page.goto(portal.url, { waitUntil: 'domcontentloaded' });
    const limite = Date.now() + (cfg.esperarLoginMinutos || 5) * 60000;
    while (!(await portal.logado(page))) {
      if (Date.now() > limite) throw new Error('login não concluído a tempo');
      console.log(`[${seg}] faça o login na janela aberta (inclusive o token); estou esperando...`);
      await page.waitForTimeout(5000);
    }
    // o portal chama salvar(download, dataDoPagamento, id) para cada extrato encontrado
    const salvar = async (download, data, id) => {
      const chave = id || `${dd(data)}|${download.suggestedFilename()}`;
      if (reg[seg].includes(chave)) return false;
      const ext = path.extname(download.suggestedFilename()) || '.pdf';
      const nome = `${seg.toUpperCase()}_EXTRATO_${dd(data)}${id ? '_' + String(id).replace(/[^\w-]/g, '') : ''}${ext}`;
      fs.mkdirSync(cfg.pasta, { recursive: true });
      await download.saveAs(path.join(cfg.pasta, nome));
      reg[seg].push(chave);
      baixados++;
      console.log(`[${seg}] salvo ${nome}`);
      return true;
    };
    await portal.baixar({ page, desde, salvar });
  } catch (e) {
    console.error(`[${seg}] ERRO: ${e.message}`);
    await page.screenshot({ path: path.join(aqui, 'perfis', `${seg}-erro.png`) }).catch(() => {});
  } finally {
    fs.mkdirSync(path.dirname(registro), { recursive: true });
    fs.writeFileSync(registro, JSON.stringify(reg, null, 1));
    await ctx.close();
  }
  console.log(`[${seg}] ${baixados} extrato(s) novo(s).`);
}

const lista = alvo === 'todas' ? cfg.seguradoras : [alvo];
for (const seg of lista) await rodar(seg);
