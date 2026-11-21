import { Injectable, computed, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map, of, tap } from 'rxjs';
import { Api } from './api';
import { UsuarioEu } from './models';

/** Usuário logado e o que ele pode ver (menu e rotas). O servidor é quem garante; aqui só se esconde. */
@Injectable({ providedIn: 'root' })
export class Perfil {
  private api = inject(Api);
  readonly eu = signal<UsuarioEu | null>(null);
  readonly admin = computed(() => this.eu()?.papel === 'admin');
  readonly leitor = computed(() => !!this.eu()?.somente_leitura);

  carregar() {
    return this.api.eu().pipe(tap((u) => this.eu.set(u)));
  }

  pode(area: string) {
    const u = this.eu();
    return !!u && (u.papel === 'admin' || u.areas.includes(area));
  }

  limpar() {
    this.eu.set(null);
  }
}

/** Rota com data.area: só entra quem tem a área; data.admin: só administrador. */
export const porArea: CanActivateFn = (rota) => {
  const perfil = inject(Perfil);
  const router = inject(Router);
  const checar = () => {
    let area = rota.data?.['area'] as string | undefined;
    if (area === 'titulos') area = rota.params['tipo'] === 'receber' ? 'receber' : 'pagar';
    const soAdmin = !!rota.data?.['admin'];
    if (soAdmin ? perfil.admin() : !area || perfil.pode(area)) return true;
    const primeira = ROTAS_POR_AREA.find(([a]) => perfil.pode(a));
    return router.parseUrl(primeira ? primeira[1] : '/sem-acesso');
  };
  return perfil.eu() ? of(checar()) : perfil.carregar().pipe(map(checar));
};

export const ROTAS_POR_AREA: [string, string][] = [
  ['painel', '/painel'],
  ['comissoes', '/comissoes'],
  ['comissao_produtoras', '/comissao-produtoras'],
  ['minha_comissao', '/minha-comissao'],
  ['previsao', '/previsao'],
  ['pagar', '/titulos/pagar'],
  ['receber', '/titulos/receber'],
  ['recorrencias', '/recorrencias'],
  ['lancamentos', '/lancamentos'],
  ['conciliacao', '/conciliacao'],
  ['plano_contas', '/plano-contas'],
  ['entidades', '/entidades'],
  ['decisoes', '/decisoes'],
  ['aprendizado', '/aprendizado'],
];
