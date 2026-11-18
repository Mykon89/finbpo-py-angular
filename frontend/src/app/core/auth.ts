import { HttpClient, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, tap, throwError } from 'rxjs';

const CHAVE = 'finbpo.token';

function lerToken(): string | null {
  try {
    return localStorage.getItem(CHAVE);
  } catch {
    return null;
  }
}

@Injectable({ providedIn: 'root' })
export class Auth {
  private http = inject(HttpClient);
  private router = inject(Router);
  readonly token = signal<string | null>(lerToken());

  login(email: string, senha: string) {
    const corpo = new URLSearchParams({ username: email, password: senha });
    return this.http
      .post<{ access_token: string }>('/api/auth/login', corpo.toString(), {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      })
      .pipe(tap((r) => this.salvar(r.access_token)));
  }

  primeiroAcesso(nome: string, email: string, senha: string) {
    return this.http.post('/api/auth/primeiro-acesso', { nome, email, senha });
  }

  sair() {
    this.salvar(null);
    this.router.navigateByUrl('/login');
  }

  private salvar(token: string | null) {
    this.token.set(token);
    try {
      if (token) localStorage.setItem(CHAVE, token);
      else localStorage.removeItem(CHAVE);
    } catch {
      /* armazenamento indisponível: mantém só em memória */
    }
  }
}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(Auth);
  const token = auth.token();
  const r = token ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;
  return next(r).pipe(
    catchError((err: HttpErrorResponse) => {
      if (err.status === 401 && !req.url.endsWith('/auth/login')) auth.sair();
      return throwError(() => err);
    }),
  );
};

export const autenticado: CanActivateFn = () => {
  return inject(Auth).token() ? true : inject(Router).parseUrl('/login');
};

export function mensagemErro(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    const d = err.error?.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) return d.map((x) => x.msg).join('; ');
    return `Erro ${err.status}`;
  }
  return 'Erro inesperado';
}
