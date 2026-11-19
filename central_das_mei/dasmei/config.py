"""Configuração local do robô (arquivo TOML) + configuração editável pelo gestor.

Senhas e chaves NÃO ficam neste arquivo: ficam no Cofre de Credenciais do
Windows (ver segredos.py).
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path


def pasta_app() -> Path:
    base = os.environ.get("DASMEI_HOME") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share"), "CentralDasMei")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def caminho_config() -> Path:
    return Path(os.environ.get("DASMEI_CONFIG") or (pasta_app() / "config.toml"))


@dataclass
class Rotina:
    """Parâmetros da rotina. Os valores do arquivo são o padrão; o que for
    salvo na tela 'Central de DAS MEI' do gestor prevalece."""
    horario: str = "07:00"
    dias_semana: list = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])  # 0 = segunda
    meses_retroativos: int = 12
    emitir_competencia_atual: bool = True      # DAS do mês anterior (vence dia 20)
    emitir_vencidos: bool = True               # gera guia atualizada de competências vencidas
    consultar_pagamentos: bool = True          # PAGTOWEB: confirma pagamentos
    pausado: bool = False
    excluidos: list = field(default_factory=list)  # ids de empresas fora do robô
    somente: list = field(default_factory=list)    # se preenchido, processa só estes ids

    def mesclar(self, remoto: dict | None) -> "Rotina":
        if not remoto:
            return self
        ok = {f.name for f in fields(self)}
        dados = {k: v for k, v in remoto.items() if k in ok and v is not None}
        try:
            r = replace(self, **dados)
            r.validar()
            return r
        except (TypeError, ValueError):
            return self

    def validar(self):
        h, m = self.horario.split(":")
        if not (0 <= int(h) < 24 and 0 <= int(m) < 60):
            raise ValueError("horário inválido")
        if not (1 <= int(self.meses_retroativos) <= 60):
            raise ValueError("meses retroativos deve ficar entre 1 e 60")
        if any(int(d) not in range(7) for d in self.dias_semana) or not self.dias_semana:
            raise ValueError("dias da semana inválidos")


@dataclass
class Config:
    supabase_url: str = "https://nhrbbsgmipkwqeqqkgjj.supabase.co"
    supabase_anon_key: str = ""
    email_robo: str = ""
    serpro_ambiente: str = "nenhum"            # "nenhum" (modo assistido), "producao" ou "trial"
    contratante_cnpj: str = ""                 # CNPJ do escritório (contratou na Loja SERPRO)
    autor_cnpj: str = ""                       # quem pede os dados (normalmente o próprio escritório)
    certificado_pfx: str = ""                  # e-CNPJ A1 do escritório (.pfx/.p12)
    intervalo_min_segundos: float = 3.0        # limite de requisições à SERPRO
    pausa_entre_clientes: tuple = (2.0, 6.0)
    timeout_segundos: float = 60.0
    max_tentativas: int = 3
    limite_falhas_seguidas: int = 5            # disjuntor: portal fora do ar
    pasta_documentos: str = r"C:\CENTRAL_DAS_MEI"
    rotina: Rotina = field(default_factory=Rotina)

    @property
    def modo_assistido(self) -> bool:
        return self.serpro_ambiente == "nenhum"

    @property
    def pasta_sistema(self) -> Path:
        return pasta_app()

    @property
    def banco(self) -> Path:
        return pasta_app() / "dasmei.db"

    @property
    def pasta_backup(self) -> Path:
        return Path(self.pasta_documentos) / "_SISTEMA" / "backups"

    @property
    def pasta_relatorios(self) -> Path:
        return Path(self.pasta_documentos) / "_SISTEMA" / "relatorios"


def carregar(caminho: Path | None = None) -> Config:
    p = Path(caminho or caminho_config())
    if not p.exists():
        raise FileNotFoundError(
            f"Configuração não encontrada em {p}. Rode: python -m dasmei configurar")
    with open(p, "rb") as f:
        d = tomllib.load(f)
    g, s, pa, rb = d.get("gestor", {}), d.get("serpro", {}), d.get("pastas", {}), d.get("rotina", {})
    cfg = Config(
        supabase_url=g.get("supabase_url", Config.supabase_url),
        supabase_anon_key=g.get("supabase_anon_key", ""),
        email_robo=g.get("email_robo", ""),
        serpro_ambiente=s.get("ambiente", "nenhum"),
        contratante_cnpj=s.get("contratante_cnpj", ""),
        autor_cnpj=s.get("autor_cnpj", "") or s.get("contratante_cnpj", ""),
        certificado_pfx=s.get("certificado_pfx", ""),
        intervalo_min_segundos=float(s.get("intervalo_min_segundos", 3.0)),
        timeout_segundos=float(s.get("timeout_segundos", 60.0)),
        pasta_documentos=pa.get("documentos", Config.pasta_documentos),
    )
    cfg.rotina = Rotina().mesclar(rb)
    if cfg.serpro_ambiente not in ("nenhum", "producao", "trial"):
        raise ValueError("serpro.ambiente deve ser 'nenhum', 'producao' ou 'trial'")
    return cfg


MODELO = """# Central de DAS MEI — configuração do robô
# Senhas e chaves NÃO ficam aqui: ficam no Cofre de Credenciais do Windows.

[gestor]
supabase_url = "{supabase_url}"
supabase_anon_key = "{supabase_anon_key}"
email_robo = "{email_robo}"

[serpro]
ambiente = "{serpro_ambiente}"          # "nenhum" = modo assistido (sem contrato SERPRO) | "producao" | "trial"
contratante_cnpj = "{contratante_cnpj}"
autor_cnpj = "{autor_cnpj}"
certificado_pfx = '{certificado_pfx}'
intervalo_min_segundos = 3

[pastas]
documentos = '{pasta_documentos}'

[rotina]   # padrões; a tela do gestor pode alterar
horario = "07:00"
meses_retroativos = 12
emitir_competencia_atual = true
emitir_vencidos = true
consultar_pagamentos = true
"""


def salvar(cfg: Config, caminho: Path | None = None) -> Path:
    p = Path(caminho or caminho_config())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(MODELO.format(**{f.name: getattr(cfg, f.name) for f in fields(cfg) if f.name != "rotina"}),
                 encoding="utf-8")
    return p
