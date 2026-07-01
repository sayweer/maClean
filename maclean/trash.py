"""Çöp Kutusu'na taşıma sarmalayıcısı.

Bu modülün TEK görevi, verilen yolları macOS Çöp Kutusu'na taşımaktır.
KALICI SİLME YOKTUR — os.remove / shutil.rmtree bilinçli olarak kullanılmaz;
tüm işlemler geri alınabilir olmalıdır. GUI'den bağımsızdır.
"""

from __future__ import annotations

import logging
from pathlib import Path

from send2trash import send2trash

logger = logging.getLogger(__name__)


def move_to_trash(
    paths: list[Path],
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Verilen yolları tek tek Çöp Kutusu'na taşır.

    Döndürür: (başarıyla_taşınanlar, [(taşınamayan_yol, hata_mesajı), ...]).

    Her yol kendi try/except'i içinde işlenir; biri başarısız olsa bile
    (izin hatası, dosya zaten yok vb.) diğerlerine devam edilir — tek bir
    hatalı öğe tüm temizliği durdurmaz.
    """
    succeeded: list[Path] = []
    failed: list[tuple[Path, str]] = []

    for path in paths:
        try:
            send2trash(str(path))
            succeeded.append(path)
        except Exception as exc:  # noqa: BLE001 - tek öğe hatası temizliği durdurmamalı
            logger.warning("Çöp'e taşınamadı: %s (%s)", path, exc)
            failed.append((path, str(exc)))

    return succeeded, failed
