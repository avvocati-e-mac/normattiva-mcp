"""Schemi MCP e conversioni di esiti, senza logica di trasporto o strumenti."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .client import ClienteNormattiva
from .esiti import Abrogato, Articolo, Esito, Preambolo
from .protezione import RapportoRete


class RapportoReteOutput(BaseModel):
    """Parte serializzabile del rapporto SQLite, senza dati di ricerca."""

    origine: str
    acquisita_il: str | None = None
    attivita: str
    consumo_attivita: str
    consumo_globale: str
    richieste_residue: int
    cooldown_fino: str | None = None
    ultimo_incidente: str | None = None
    livello: str
    avviso: str


class ProtezioneReteOutput(RapportoReteOutput):
    """Stato corrente e operazioni distinte, incluso un recupero storico."""

    rapporti: list[RapportoReteOutput] = Field(default_factory=list)


class EsitoOutput(BaseModel):
    """Schema comune per articolo, abrogato e preambolo."""

    esito: str
    urn: str
    permalink: str
    heading: str | None = None
    testo: str | None = None
    aggiornamenti: list[str] = Field(default_factory=list)
    vigenza_storica: dict[str, str] | None = None
    messaggio: str | None = None
    data_abrogazione: str | None = None
    caratteri: int | None = None
    incipit: str | None = None
    attribuzione: str
    avvisi: list[str] = Field(default_factory=list)
    protezione_rete: ProtezioneReteOutput


class LinkOutput(BaseModel):
    markdown: str
    verificato: bool | None
    avviso: str | None = None
    avvisi: list[str] = Field(default_factory=list)
    protezione_rete: ProtezioneReteOutput


class FonteOutput(BaseModel):
    trovata: bool
    disponibile: bool | None = None
    nome_canonico: str | None = None
    tipo: str | None = None
    numero: int | None = None
    data: str | None = None
    allegato: int | None = None
    stato: str | None = None
    nota_stato: str | None = None
    alias: list[str] = Field(default_factory=list)
    nota: str | None = None


class StatoReteOutput(BaseModel):
    rapporto: ProtezioneReteOutput
    aggregati_giornalieri: dict[str, int | str | None]


def _rapporto_a_output(rapporto: RapportoRete) -> RapportoReteOutput:
    return RapportoReteOutput(**rapporto.modello())


def protezione_rete(
    client: ClienteNormattiva, *, stato_locale: bool = False
) -> ProtezioneReteOutput:
    """Rende sempre visibile il coordinatore, anche per una sola operazione locale."""
    if stato_locale:
        assert client.protezione is not None
        ultimo = client.protezione.stato()
        rapporti: list[RapportoReteOutput] = []
    else:
        ultimo = client.ultimo_rapporto
        rapporti = [_rapporto_a_output(rapporto) for rapporto in client.ultimi_rapporti]
    return ProtezioneReteOutput(**ultimo.modello(), rapporti=rapporti)


def avvisi_rapporti(client: ClienteNormattiva) -> list[str]:
    """Ogni tentativo HTTP reale deve lasciare la sua frase-quota leggibile."""
    return [rapporto.avviso for rapporto in client.ultimi_rapporti if rapporto.origine == "rete"]


def esito_a_output(
    esito: Esito,
    protezione: ProtezioneReteOutput,
    avvisi_extra: tuple[str, ...] = (),
) -> EsitoOutput:
    """Mantiene avvertenze e attribuzione in tutte le varianti dell'esito."""
    avvisi = list(avvisi_extra)
    if isinstance(esito, Articolo):
        vigenza_storica = None
        if esito.vigenza_storica:
            vigenza_storica = {
                "data": esito.vigenza_storica.data.isoformat(),
                "avviso": esito.vigenza_storica.avviso,
            }
            avvisi.append(esito.vigenza_storica.avviso)
        return EsitoOutput(
            esito="articolo",
            urn=esito.urn.stringa,
            permalink=esito.permalink,
            heading=esito.heading,
            testo=esito.testo,
            aggiornamenti=list(esito.aggiornamenti),
            vigenza_storica=vigenza_storica,
            attribuzione=esito.attribuzione,
            avvisi=avvisi,
            protezione_rete=protezione,
        )
    if isinstance(esito, Abrogato):
        avvisi.append(f"Articolo abrogato: {esito.messaggio}")
        return EsitoOutput(
            esito="abrogato",
            urn=esito.urn.stringa,
            permalink=esito.permalink,
            messaggio=esito.messaggio,
            data_abrogazione=esito.data_abrogazione.isoformat() if esito.data_abrogazione else None,
            attribuzione=esito.attribuzione,
            avvisi=avvisi,
            protezione_rete=protezione,
        )
    assert isinstance(esito, Preambolo)
    avvisi.append(
        "Attenzione: Normattiva ha restituito il preambolo di promulgazione, "
        "non l'articolo richiesto."
    )
    return EsitoOutput(
        esito="preambolo",
        urn=esito.urn.stringa,
        permalink=esito.permalink,
        caratteri=esito.caratteri,
        incipit=esito.incipit,
        attribuzione=esito.attribuzione,
        avvisi=avvisi,
        protezione_rete=protezione,
    )


__all__ = [
    "EsitoOutput",
    "FonteOutput",
    "LinkOutput",
    "ProtezioneReteOutput",
    "RapportoReteOutput",
    "StatoReteOutput",
    "avvisi_rapporti",
    "esito_a_output",
    "protezione_rete",
]
