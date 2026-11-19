import { Routes } from '@angular/router';
import { autenticado } from './core/auth';
import { porArea } from './core/perfil';
import { Shell } from './layout/shell';

const pagina = (path: string, area: string, carregar: () => Promise<unknown>, admin = false) => ({
  path,
  canActivate: [porArea],
  data: admin ? { admin: true } : { area },
  loadComponent: carregar as never,
});

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./pages/login').then((m) => m.Login) },
  {
    path: '',
    component: Shell,
    canActivate: [autenticado],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'painel' },
      pagina('painel', 'painel', () => import('./pages/painel').then((m) => m.Painel)),
      pagina('titulos/:tipo', 'titulos', () => import('./pages/titulos').then((m) => m.Titulos)),
      pagina('importar', 'lancamentos', () => import('./pages/importar').then((m) => m.Importar)),
      pagina('lancamentos', 'lancamentos', () =>
        import('./pages/lancamentos').then((m) => m.Lancamentos),
      ),
      pagina('recorrencias', 'recorrencias', () =>
        import('./pages/recorrencias').then((m) => m.Recorrencias),
      ),
      pagina('comissoes', 'comissoes', () => import('./pages/comissoes').then((m) => m.Comissoes)),
      pagina('previsao', 'previsao', () =>
        import('./pages/previsao').then((m) => m.PrevisaoRecebimentos),
      ),
      pagina('plano-contas', 'plano_contas', () =>
        import('./pages/plano-contas').then((m) => m.PlanoContas),
      ),
      pagina('conciliacao', 'conciliacao', () =>
        import('./pages/conciliacao').then((m) => m.Conciliacao),
      ),
      pagina('entidades', 'entidades', () => import('./pages/entidades').then((m) => m.Entidades)),
      pagina('fechamento-mes', 'painel', () =>
        import('./pages/fechamento-mes').then((m) => m.FechamentoMes),
      ),
      pagina('decisoes', 'decisoes', () => import('./pages/decisoes').then((m) => m.Decisoes)),
      pagina('aprendizado', 'aprendizado', () =>
        import('./pages/aprendizado').then((m) => m.Aprendizado),
      ),
      pagina('acessos', '', () => import('./pages/acessos').then((m) => m.Acessos), true),
      pagina('auditoria', '', () => import('./pages/auditoria').then((m) => m.AuditoriaPage), true),
      pagina(
        'privacidade',
        '',
        () => import('./pages/privacidade').then((m) => m.Privacidade),
        true,
      ),
      {
        path: 'sem-acesso',
        loadComponent: () => import('./pages/sem-acesso').then((m) => m.SemAcesso),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
