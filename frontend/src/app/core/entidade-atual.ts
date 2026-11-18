import { Injectable, computed, inject, signal } from '@angular/core';
import { Api } from './api';
import { Entidade } from './models';

const CHAVE = 'finbpo.entidade';

@Injectable({ providedIn: 'root' })
export class EntidadeAtual {
  private api = inject(Api);
  readonly lista = signal<Entidade[]>([]);
  readonly id = signal<number | null>(this.lerSalvo());
  readonly atual = computed(() => this.lista().find((e) => e.id === this.id()) ?? null);

  carregar() {
    this.api.entidades().subscribe((l) => {
      this.lista.set(l);
      if (!l.some((e) => e.id === this.id())) this.selecionar(l[0]?.id ?? null);
    });
  }

  selecionar(id: number | null) {
    this.id.set(id);
    try {
      if (id) localStorage.setItem(CHAVE, String(id));
    } catch {
      /* ignora */
    }
  }

  private lerSalvo(): number | null {
    try {
      const v = localStorage.getItem(CHAVE);
      return v ? Number(v) : null;
    } catch {
      return null;
    }
  }
}
