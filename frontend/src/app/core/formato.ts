import { Pipe, PipeTransform } from '@angular/core';

const moeda = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

export function brl(v: string | number | null | undefined): string {
  return v === null || v === undefined ? '—' : moeda.format(Number(v));
}

export function dataBr(iso: string | null | undefined): string {
  if (!iso) return '—';
  const [a, m, d] = iso.slice(0, 10).split('-');
  return `${d}/${m}/${a}`;
}

export function soDigitos(v: string | null | undefined): string {
  return (v ?? '').replace(/\D/g, '');
}

export function documentoFormatado(v: string | null | undefined): string {
  const d = soDigitos(v);
  if (d.length === 14) return d.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, '$1.$2.$3/$4-$5');
  if (d.length === 11) return d.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, '$1.$2.$3-$4');
  return v ?? '';
}

export function hojeIso(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

@Pipe({ name: 'brl' })
export class BrlPipe implements PipeTransform {
  transform(v: string | number | null | undefined): string {
    return brl(v);
  }
}

@Pipe({ name: 'documento' })
export class DocumentoPipe implements PipeTransform {
  transform(v: string | null | undefined): string {
    return documentoFormatado(v) || '—';
  }
}

@Pipe({ name: 'dataBr' })
export class DataBrPipe implements PipeTransform {
  transform(v: string | null | undefined): string {
    return dataBr(v);
  }
}
