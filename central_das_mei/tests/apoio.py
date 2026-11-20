"""Ferramentas de teste: PDFs fictícios e uma SERPRO falsa (httpx.MockTransport)."""
import base64
import json

import httpx

from dasmei.cnpj import formatar, gerar_com_dv

CNPJ_A = gerar_com_dv("112223330001")   # fictícios, com dígitos válidos
CNPJ_B = gerar_com_dv("445556660001")
CNPJ_C = gerar_com_dv("778889990001")


def pdf_texto(linhas):
    """PDF mínimo e válido (Helvetica) com as linhas de texto dadas."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    conteudo = "BT /F1 10 Tf 40 800 Td 14 TL " + " ".join(f"({esc(l)}) '" for l in linhas) + " ET"
    conteudo_b = conteudo.encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(conteudo_b) + conteudo_b + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = b"%PDF-1.4\n"
    ofs = []
    for i, o in enumerate(objs, 1):
        ofs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in ofs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def pdf_das(cnpj, ano, mes, venc_iso, total, numero):
    from dasmei.competencia import MESES_TXT
    a, m, d = venc_iso.split("-")
    nd = numero
    return pdf_texto([
        "Documento de Arrecadacao do Simples Nacional",
        f"CNPJ {formatar(cnpj)}  Razao Social EMPRESA FICTICIA",
        f"Periodo de Apuracao {MESES_TXT[mes - 1].replace('ç', 'c')}/{ano}",
        f"Pagar este documento ate {d}/{m}/{a}",
        f"Numero do Documento {nd[:2]}.{nd[2:4]}.{nd[4:]}",
        f"Valor Total do Documento {total:.2f}".replace(".", ","),
    ])


class SerproFalsa:
    """Imita o gateway Integra Contador. Comportamento por CNPJ configurável."""

    def __init__(self):
        self.pagamentos = {}       # cnpj -> lista de dicts no formato da API
        self.comportamento = {}    # cnpj -> "sem_procuracao" | "fora" | "negocio" | "pdf_ruim" | int(falhas temporárias)
        self.chamadas = []
        self.seq = 1000
        self.auth = 0

    def handler(self, req: httpx.Request):
        if req.url.path.endswith("/authenticate"):
            self.auth += 1
            return httpx.Response(200, json={"access_token": "AT", "jwt_token": "JWT", "expires_in": 2000})
        corpo = json.loads(req.content)
        cnpj = corpo["contribuinte"]["numero"]
        ped = corpo["pedidoDados"]
        dados = json.loads(ped["dados"])
        self.chamadas.append((req.url.path.rsplit("/", 1)[-1], ped["idServico"], cnpj, dados))
        comp = self.comportamento.get(cnpj)
        if comp == "sem_procuracao":
            return httpx.Response(403, json={"status": 403, "mensagens": [
                {"codigo": "[AcessoNegado-ICGERENCIADOR-022]", "texto": "Procuração inexistente para o contribuinte"}]})
        if comp == "fora":
            return httpx.Response(503, text="Service Unavailable")
        if isinstance(comp, int) and comp > 0:
            self.comportamento[cnpj] = comp - 1
            return httpx.Response(500, json={"status": 500, "mensagens": [{"codigo": "[Erro]", "texto": "erro interno"}]})
        if ped["idServico"] == "PAGAMENTOS71":
            return httpx.Response(200, json={"status": 200, "mensagens": [{"codigo": "[Sucesso-PAGTOWEB]", "texto": "ok"}],
                                             "dados": json.dumps(self.pagamentos.get(cnpj, [])[
                                                 dados.get("primeiroDaPagina", 0):dados.get("primeiroDaPagina", 0) + dados.get("tamanhoDaPagina", 100)])})
        if ped["idServico"] == "GERARDASPDF21":
            pa = dados["periodoApuracao"]
            if comp == "negocio":
                return httpx.Response(400, json={"status": 400, "mensagens": [
                    {"codigo": "[EntradaIncorreta-PGMEI-001]", "texto": "Período de apuração não permitido"}]})
            ano, mes = int(pa[:4]), int(pa[4:])
            pm = (ano * 12 + mes) % 12 + 1
            pa_ = ano + (1 if mes == 12 else 0)
            venc = f"{pa_}-{pm:02d}-20"
            self.seq += 1
            numero = f"07202{self.seq:012d}"
            total = 81.05
            pdf = b"isto nao e pdf" if comp == "pdf_ruim" else pdf_das(cnpj, ano, mes, venc, total, numero)
            item = {"pdf": base64.b64encode(pdf).decode(), "cnpjCompleto": cnpj, "razaoSocial": "EMPRESA FICTICIA",
                    "detalhamento": [{"periodoApuracao": pa, "numeroDocumento": numero,
                                      "dataVencimento": venc.replace("-", ""), "dataLimiteAcolhimento": "20991231",
                                      "valores": {"principal": 81.05, "multa": 0, "juros": 0, "total": total},
                                      "observacao1": "", "composicao": []}]}
            return httpx.Response(200, json={"status": 200, "mensagens": [{"codigo": "[Sucesso-PGMEI]", "texto": "ok"}],
                                             "dados": json.dumps([item])})
        return httpx.Response(404)

    def transporte(self):
        return httpx.MockTransport(self.handler)
