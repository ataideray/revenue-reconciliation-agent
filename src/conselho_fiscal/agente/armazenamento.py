"""Armazenamento do agente numa pasta local (no Azure: Blob + Table).

    <base>/
      estado.json                  envio em andamento (arquivos ainda incompletos)
      envio/                       arquivos recebidos, à espera dos outros
      conversas/<papel>.jsonl      histórico de cada conversa
      canais/whatsapp.json         avisos do WhatsApp já tratados e o papel da vez
      cadastros/                   cópia própria dos cadastros (só no simulador)
      meses/AAAA-MM/
        estado.json                situação, versões, divergências e notas
        v1/, v2/…                  arquivos de cada versão e a planilha gerada
          entrega1/, entrega2/…    cópia fixa da planilha que o CF recebeu

Todos os caminhos guardados no estado são relativos à base.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from conselho_fiscal import config


def agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Armazenamento:
    def __init__(self, base: str | Path | None = None):
        self.base = Path(base or config.diretorio_agente()).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    # ---------- caminhos ----------

    def caminho(self, relativo: str) -> Path:
        """Caminho absoluto de um caminho relativo à base; recusa sair da base."""
        p = (self.base / relativo).resolve()
        if not p.is_relative_to(self.base):
            raise ValueError(f"caminho fora da pasta do agente: {relativo}")
        return p

    def relativo(self, caminho: str | Path) -> str:
        return Path(caminho).resolve().relative_to(self.base).as_posix()

    def pasta_versao(self, mes: str, versao: int) -> Path:
        p = self.base / "meses" / mes / f"v{versao}"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ---------- arquivos recebidos ----------

    def guardar_recebido(self, nome: str, conteudo: bytes) -> Path:
        """Grava um anexo recebido em envio/, sem sobrescrever outro."""
        pasta = self.base / "envio"
        pasta.mkdir(exist_ok=True)
        nome = os.path.basename(nome) or "arquivo"
        destino = pasta / f"{datetime.now():%Y%m%d-%H%M%S-%f}_{nome}"
        destino.write_bytes(conteudo)
        return destino

    def cadastros_proprios(self) -> tuple[Path, Path]:
        """Cópia dos cadastros dentro da pasta do agente: o que se testa no
        simulador não toca os cadastros reais. Na 1ª vez, copia o
        destinos.json real e começa os vínculos vazios. Retorna os caminhos
        (destinos, vínculos)."""
        pasta = self.base / "cadastros"
        pasta.mkdir(exist_ok=True)
        destinos, vinculos_ = pasta / "destinos.json", pasta / "vinculos_confirmados.json"
        if not destinos.exists():
            shutil.copy(config.caminho_destinos(), destinos)
        if not vinculos_.exists():
            vinculos_.write_text("[]\n", encoding="utf-8")
        return destinos, vinculos_

    def mover(self, origem: str | Path, destino: str | Path) -> Path:
        Path(destino).parent.mkdir(parents=True, exist_ok=True)
        return Path(shutil.move(str(origem), str(destino)))

    # ---------- estado ----------

    def _ler_json(self, p: Path, padrao: Any) -> Any:
        if not p.exists():
            return padrao
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def _gravar_json(self, p: Path, dados: Any) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, p)       # gravação atômica: nunca deixa o estado pela metade

    def estado_geral(self) -> dict[str, Any]:
        return self._ler_json(self.base / "estado.json", {"envio": {}})

    def salvar_estado_geral(self, estado: dict[str, Any]) -> None:
        self._gravar_json(self.base / "estado.json", estado)

    def estado_canal(self, canal: str, padrao: dict[str, Any]) -> dict[str, Any]:
        """Estado de um canal (WhatsApp): avisos já tratados, papel da vez."""
        return self._ler_json(self.base / "canais" / f"{canal}.json", padrao)

    def salvar_estado_canal(self, canal: str, estado: dict[str, Any]) -> None:
        self._gravar_json(self.base / "canais" / f"{canal}.json", estado)

    def estado_mes(self, mes: str) -> dict[str, Any] | None:
        return self._ler_json(self.base / "meses" / mes / "estado.json", None)

    def salvar_estado_mes(self, estado: dict[str, Any]) -> None:
        self._gravar_json(self.base / "meses" / estado["mes"] / "estado.json", estado)

    def meses(self) -> list[str]:
        pasta = self.base / "meses"
        return sorted(p.name for p in pasta.iterdir()
                      if (p / "estado.json").exists()) if pasta.exists() else []

    # ---------- conversas ----------

    def registrar_mensagem(self, papel: str, mensagem: dict[str, Any]) -> None:
        p = self.base / "conversas" / f"{papel}.jsonl"
        p.parent.mkdir(exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(mensagem, ensure_ascii=False) + "\n")

    def conversa(self, papel: str) -> list[dict[str, Any]]:
        p = self.base / "conversas" / f"{papel}.jsonl"
        if not p.exists():
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(linha) for linha in f if linha.strip()]
