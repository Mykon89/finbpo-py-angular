import { brl, dataBr } from './formato';

describe('formato', () => {
  it('formata moeda em BRL', () => {
    expect(brl('1234.5').replace(/\s/g, ' ')).toBe('R$ 1.234,50');
    expect(brl(null)).toBe('—');
  });
  it('formata data ISO em dd/mm/aaaa', () => {
    expect(dataBr('2026-10-05')).toBe('05/10/2026');
  });
});
