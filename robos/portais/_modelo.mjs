// Modelo de robô de portal. Copie para portais/<seguradora>.mjs (ex.: porto.mjs) e preencha.
// O jeito mais rápido: rode "npm run gravar -- https://portal-da-seguradora" , faça o caminho
// até baixar um extrato e me envie o código que o Playwright gerou. Eu transformo neste formato.

export const url = 'https://portal.exemplo.com.br/corretor';

// true quando já está dentro do portal (ex.: o menu do corretor aparece)
export async function logado(page) {
  return page.getByText('Sair', { exact: false }).isVisible().catch(() => false);
}

// Vai até a tela de extratos e baixa os pagos a partir de "desde".
// Para cada extrato: const download = await Promise.all([page.waitForEvent('download'), botao.click()]).then(r => r[0]);
//                    await salvar(download, dataDoPagamento, numeroDoExtrato);
export async function baixar({ page, desde, salvar }) {
  await page.getByRole('link', { name: /comiss/i }).click();
  await page.getByRole('link', { name: /extrato/i }).click();
  const linhas = page.locator('table tbody tr');
  for (let i = 0; i < (await linhas.count()); i++) {
    const l = linhas.nth(i);
    const [d, m, a] = (await l.locator('td').nth(0).innerText()).trim().split('/');
    const data = new Date(+a, +m - 1, +d);
    if (data < desde) continue;
    const [download] = await Promise.all([page.waitForEvent('download'), l.getByRole('button', { name: /baixar|download/i }).click()]);
    await salvar(download, data, (await l.locator('td').nth(1).innerText()).trim());
  }
}
