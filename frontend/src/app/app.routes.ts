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
