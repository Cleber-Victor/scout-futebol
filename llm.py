"""Camada do LLM: o ÚNICO arquivo que sabe qual provedor está sendo usado.

Usamos o Gemini pela interface compatível com a biblioteca `openai`. Por quê:
  - a mesma biblioteca fala com OpenAI, Gemini, modelos locais (Ollama) etc.;
  - trocar de provedor = mudar base_url, chave e modelo AQUI, sem tocar no agente.

Configuração: um arquivo .env na raiz do projeto (já está no .gitignore; NUNCA commitar):
  GEMINI_API_KEY=sua-chave                 # https://aistudio.google.com/apikey
  MODELO_LLM=gemini-3.5-flash              # versão FIXA, não "-latest": se o Google trocar o
                                           # modelo por trás do apelido, a avaliação (etapa 5)
                                           # muda sem você ter mudado nada
Variáveis exportadas no terminal também funcionam e têm prioridade sobre o .env.
"""
import os
from functools import cache

from dotenv import load_dotenv
from openai import APIError, OpenAI

load_dotenv()  # lê o .env para os.environ (sem sobrescrever o que já foi exportado)

BASE_URL_GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _variavel(nome: str) -> str:
    """Lê uma variável de ambiente obrigatória, com uma mensagem que diz como resolver.
    Por quê: um KeyError seco no meio do agente é difícil de entender."""
    valor = os.environ.get(nome, "").strip()
    if not valor:
        raise RuntimeError(f"Variável {nome} não definida. Coloque {nome}=... no arquivo .env "
                           f"na raiz do projeto (veja o topo do llm.py).")
    return valor


@cache  # cria o cliente uma vez só e reaproveita a conexão HTTP nas próximas chamadas
def _cliente() -> OpenAI:
    return OpenAI(api_key=_variavel("GEMINI_API_KEY"), base_url=BASE_URL_GEMINI)


def conversar(mensagens: list[dict], temperatura: float = 0.0) -> str:
    """Envia a conversa e devolve o texto da resposta.

    mensagens: [{"role": "system" | "user" | "assistant", "content": "..."}]
    temperatura 0: queremos o SQL mais provável, não criatividade. Também deixa a avaliação
    (etapa 5) mais reproduzível.
    """
    try:
        resposta = _cliente().chat.completions.create(
            model=_variavel("MODELO_LLM"),
            messages=mensagens,
            temperature=temperatura,
        )
    except APIError as erro:
        # A biblioteca já tenta de novo sozinha em erros temporários (503, 429). Se chegou
        # aqui, desistiu. Viramos RuntimeError para o agente não precisar conhecer as
        # exceções do provedor (trocar de provedor = mudar só este arquivo).
        raise RuntimeError(f"falha na API do LLM ({type(erro).__name__}): {erro}") from erro
    # content pode vir None (ex.: resposta bloqueada por filtro de segurança). Devolver ""
    # deixa o agente tratar como "resposta sem JSON" e pedir de novo, em vez de quebrar.
    return resposta.choices[0].message.content or ""


if __name__ == "__main__":
    # Teste rápido da conexão:  python llm.py
    print(conversar([{"role": "user", "content": "Responda só: ok"}]))
