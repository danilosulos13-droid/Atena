#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "nanorobotics_sources.json"

SOURCES = [
    ("PubMed Central nanorobotics", "https://www.ncbi.nlm.nih.gov/pmc/?term=nanorobotics", "NIH / NCBI", "biomedical open-access articles"),
    ("NIH RePORTER nanotechnology", "https://reporter.nih.gov/search/nanotechnology", "NIH", "funded research projects"),
    ("ClinicalTrials.gov nanorobots", "https://clinicaltrials.gov/search?term=nanorobots", "U.S. National Library of Medicine", "clinical trial registry"),
    ("WHO nanotechnology", "https://www.who.int/teams/environment-climate-change-and-health/chemical-safety-and-health/nanotechnology", "World Health Organization", "health and safety context"),
    ("FDA nanotechnology guidance", "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/nanotechnology-guidance-documents", "U.S. FDA", "regulatory guidance"),
    ("European Medicines Agency nanomedicine", "https://www.ema.europa.eu/en/search?search_api_fulltext=nanomedicine", "European Medicines Agency", "medicines regulation"),
    ("European Commission nanomaterials", "https://single-market-economy.ec.europa.eu/sectors/chemicals/nanomaterials_en", "European Commission", "European nanomaterials policy"),
    ("OECD nanomaterials safety", "https://www.oecd.org/chemicalsafety/nanomaterials/", "OECD", "risk assessment and safety"),
    ("U.S. EPA nanotechnology", "https://www.epa.gov/chemical-research/research-and-nanotechnology", "U.S. EPA", "environmental safety"),
    ("NIST nanotechnology", "https://www.nist.gov/topics/nanotechnology", "National Institute of Standards and Technology", "measurement and standards"),
    ("NASA Technical Reports nanotechnology", "https://ntrs.nasa.gov/search?q=nanorobotics", "NASA", "aerospace technical reports"),
    ("DOE OSTI nanotechnology", "https://www.osti.gov/search/semantic:nanorobotics", "U.S. Department of Energy", "energy research repository"),
    ("NanoSafety Cluster", "https://www.nanosafetycluster.eu/", "European NanoSafety Cluster", "nanomaterial safety research"),
    ("British Society for Nanomedicine", "https://www.britishsocietynanomedicine.org/", "British Society for Nanomedicine", "nanomedicine reviews and policy"),
    ("Nanotechnology Perceptions", "https://nanotechnology.perceptions.co.uk/", "Nanotechnology Perceptions", "nanotechnology journal"),
    ("International Journal of Nanomedicine", "https://www.dovepress.com/international-journal-of-nanomedicine-journal", "Dove Medical Press", "open-access nanomedicine"),
    ("Micromachines micro nanorobots", "https://www.mdpi.com/journal/micromachines/search?q=nanorobots", "MDPI", "microfabrication and microrobotics"),
    ("Nanomaterials nanomedicine", "https://www.mdpi.com/journal/nanomaterials/search?q=nanomedicine", "MDPI", "nanomaterials and nanomedicine"),
    ("Journal of Micro-Bio Robotics", "https://link.springer.com/journal/12304", "Springer Nature", "micro-bio robotics"),
    ("Springer nanorobotics search", "https://link.springer.com/search?query=nanorobotics", "Springer Nature", "books and articles"),
    ("ScienceDirect nanorobotics search", "https://www.sciencedirect.com/search?qs=nanorobotics", "Elsevier", "articles and reviews"),
    ("Taylor & Francis nanorobotics", "https://www.tandfonline.com/action/doSearch?AllField=nanorobotics", "Taylor & Francis", "robotics and nanomedicine"),
    ("Wiley micro nanorobots", "https://onlinelibrary.wiley.com/action/doSearch?AllField=nanorobots", "Wiley", "materials and engineering"),
    ("ACS Nano search", "https://pubs.acs.org/action/doSearch?AllField=nanorobots", "American Chemical Society", "nano science and engineering"),
    ("Nature Reviews Materials search", "https://www.nature.com/search?q=microrobots", "Nature Portfolio", "materials reviews"),
    ("Harvard Wyss microrobotics", "https://wyss.harvard.edu/technology/microrobotics/", "Wyss Institute at Harvard", "bioinspired microrobotics"),
    ("MIT MicroRobotics Lab", "https://mrl.mit.edu/", "MIT", "micro robotics research"),
    ("University of Toronto Microrobotics Lab", "https://microrobotics.mie.utoronto.ca/", "University of Toronto", "microrobotics laboratory"),
    ("EPFL Laboratory of Microsystems", "https://www.epfl.ch/labs/lmh/", "EPFL", "microsystems and micro robotics"),
    ("Carnegie Mellon Robotics Institute nanorobotics", "https://www.ri.cmu.edu/", "Carnegie Mellon University", "robotics research"),
    ("Robotics Open Source Software", "https://index.ros.org/search/?q=microrobot", "Open Robotics", "robotics software discovery"),
    ("CORDIS nanorobotics", "https://cordis.europa.eu/search/en?q=nanorobotics", "European Commission", "European research projects"),
    ("Zenodo nanorobotics search", "https://zenodo.org/search?q=nanorobotics", "CERN / OpenAIRE", "datasets and research outputs"),
    ("OpenAIRE nanorobotics", "https://explore.openaire.eu/search/find?keyword=nanorobotics", "OpenAIRE", "open research graph"),
    ("CORE nanorobotics", "https://core.ac.uk/search?q=nanorobotics", "CORE", "open-access scholarly aggregator"),
    ("BASE nanorobotics", "https://www.base-search.net/Search/Results?lookfor=nanorobotics", "Bielefeld University Library", "academic search index"),
    ("Lens nanotechnology patents", "https://www.lens.org/lens/search?q=nanorobotics", "The Lens", "scholarly and patent discovery"),
]


def main() -> int:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    existing = {str(item.get("url", "")).rstrip("/") for item in payload["sources"]}
    added = 0
    for name, url, authority, scope in SOURCES:
        if url.rstrip("/") in existing:
            continue
        payload["sources"].append({
            "name": name,
            "kind": "html",
            "url": url,
            "authority": authority,
            "scope": scope,
            "access": "public page or metadata; access and license may vary",
            "weight": 0.75,
            "enabled": True,
            "keywords": ["nanorobotics", "nanorobots", "microrobotics", "nanomedicine"],
        })
        existing.add(url.rstrip("/"))
        added += 1
    payload["version"] = 2
    payload["description"] += " Catálogo curado ampliado; novas fontes descobertas automaticamente são registradas como candidatas e validadas antes de ativação."
    CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"added": added, "total": len(payload["sources"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
