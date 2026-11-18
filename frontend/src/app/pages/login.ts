import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Auth, mensagemErro } from '../core/auth';

@Component({
  selector: 'app-login',
  imports: [FormsModule],
  template: `
    <form class="cartao caixa" (ngSubmit)="enviar()">
      <h1>FinBPO</h1>
      <p class="sutil">{{ primeiro() ? 'Crie o usuário administrador' : 'Acesse sua conta' }}</p>
      @if (primeiro()) {
        <label>Nome <input name="nome" [(ngModel)]="nome" required /></label>
      }
      <label
        >E-mail
        <input name="email" type="email" [(ngModel)]="email" required autocomplete="username"
      /></label>
      <label
        >Senha
        <input
          name="senha"
          type="password"
          [(ngModel)]="senha"
          required
          minlength="8"
          autocomplete="current-password"
      /></label>
      @if (erro()) {
        <p class="erro">{{ erro() }}</p>
      }
      <button class="primario" type="submit" [disabled]="carregando()">
        {{ primeiro() ? 'Criar e entrar' : 'Entrar' }}
      </button>
      <button class="link" type="button" (click)="primeiro.set(!primeiro())">
        {{ primeiro() ? 'Já tenho usuário' : 'Primeiro acesso' }}
      </button>
    </form>
  `,
  styles: `
    :host {
      display: grid;
      place-items: center;
      min-height: 100vh;
      padding: 16px;
    }
    .caixa {
      width: 100%;
      max-width: 360px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    h1 {
      margin: 0;
    }
  `,
})
export class Login {
  private auth = inject(Auth);
  private router = inject(Router);
  nome = '';
  email = '';
  senha = '';
  primeiro = signal(false);
  erro = signal('');
  carregando = signal(false);

  enviar() {
    this.erro.set('');
    this.carregando.set(true);
    const entrar = () =>
      this.auth.login(this.email, this.senha).subscribe({
        next: () => this.router.navigateByUrl('/painel'),
        error: (e) => {
          this.erro.set(mensagemErro(e));
          this.carregando.set(false);
        },
      });
    if (this.primeiro()) {
      this.auth.primeiroAcesso(this.nome, this.email, this.senha).subscribe({
        next: entrar,
        error: (e) => {
          this.erro.set(mensagemErro(e));
          this.carregando.set(false);
        },
      });
    } else entrar();
  }
}
