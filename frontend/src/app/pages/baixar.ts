export function salvarBlob(b: Blob, nome: string) {
  const url = URL.createObjectURL(b);
  const l = document.createElement('a');
  l.href = url;
  l.download = nome;
  l.click();
  URL.revokeObjectURL(url);
}
