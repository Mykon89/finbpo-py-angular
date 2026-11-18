import { Routes } from '@angular/router';
import { autenticado } from './core/auth';
import { Shell } from './layout/shell';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./pages/login').then((m) => m.Login) },
  {
    path: '',
    component: Shell,
    canActivate: [autenticado],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'painel' },
      { path: 'painel', loadComponent: () => import('./pages/painel').then((m) => m.Painel) },
      {
        path: 'titulos/:tipo',
        loadComponent: () => import('./pages/titulos').then((m) => m.Titulos),
      },
      { path: 'importar', loadComponent: () => import('./pages/importar').then((m) => m.Importar) },
      {
        path: 'lancamentos',
        loadComponent: () => import('./pages/lancamentos').then((m) => m.Lancamentos),
      },
      {
        path: 'recorrencias',
        loadComponent: () => import('./pages/recorrencias').then((m) => m.Recorrencias),
      },
      {
        path: 'comissoes',
        loadComponent: () => import('./pages/comissoes').then((m) => m.Comissoes),
      },
      {
        path: 'previsao',
        loadComponent: () => import('./pages/previsao').then((m) => m.PrevisaoRecebimentos),
      },
      {
        path: 'plano-contas',
        loadComponent: () => import('./pages/plano-contas').then((m) => m.PlanoContas),
      },
      {
        path: 'conciliacao',
        loadComponent: () => import('./pages/conciliacao').then((m) => m.Conciliacao),
      },
      {
        path: 'entidades',
        loadComponent: () => import('./pages/entidades').then((m) => m.Entidades),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
