"""Chat patlaması algılayıcı.

Mantık (videodaki gibi): her N saniyede gelen chat mesajını say. Normal hızın
birkaç katına çıktığı an = yayında bir şey oldu. Gülme/şok mesajları ekstra puan.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, deque
from dataclasses import dataclass, field

# Gülme / şok / "klip at" tepkileri — bunlar daha değerli
HYPE = {
    "lol", "lmao", "lmfao", "kekw", "omegalul", "lul", "icant", "xd", "haha", "ahah",
    "clip", "clipit", "clipthat", "nah", "no way", "noway", "wtf", "omg", "w", "dead",
    "💀", "😂", "🤣", "pog", "pogchamp", "poggers", "monkas", "holy", "insane",
    "ajsdk", "skull", "bruh", "xdd", "lmaooo", "sjsj", "jsjs", "aşdk", "asdasd",
    "gg", "?", "??", "???", "help", "ripbozo", "rip",
}
_KUTLAMA = ("gift", "subscri", "resub", "raid", "welcome", "hoş geldin", "hosgeldin", "abone",
            "bağış", "donat", "hype train", "giveaway", "çekiliş", "cekilis", "happy birthday", "doğum günü")
_word = re.compile(r"[\w💀😂🤣?]+", re.UNICODE)


def mesaj_puani(text: str) -> tuple[float, str | None]:
    """Mesaj başına puan (1 + tepki bonusu) ve bulunan tepki kelimesi."""
    t = text.lower().strip()
    # komik bir an değil: bot komutları (!giveaway), oylama (1 / 2), abone/bağış/raid tebrikleri
    if t.startswith("!"):
        return 0.0, None
    if t.replace(" ", "").isdigit():
        return 0.2, None
    if any(k in t for k in _KUTLAMA):
        return 0.3, None
    tokens = _word.findall(t)
    for tok in tokens:
        if tok in HYPE or tok.startswith(("lmao", "kekw", "omegalul", "haha", "xdd")):
            return 1.5, tok
    if "clip" in t:
        return 2.0, "clip"
    return 1.0, None


_ALFABE = {"ar": ("\u0600", "\u06FF"), "ru": ("\u0400", "\u04FF"), "ko": ("\uAC00", "\uD7AF"),
           "ja": ("\u3040", "\u30FF"), "zh": ("\u4E00", "\u9FFF"), "th": ("\u0E00", "\u0E7F"),
           "he": ("\u0590", "\u05FF"), "hi": ("\u0900", "\u097F")}


def yazi_dili(mesajlar: list[str], oran: float = 0.35) -> str:
    """Chat mesajlarının önemli kısmı Latin olmayan bir alfabeyle mi yazılmış? (Arapça, Rusça...) Değilse ""."""
    if not mesajlar:
        return ""
    sayac: dict[str, int] = {}
    for m in mesajlar:
        for dil, (a, b) in _ALFABE.items():
            if sum(1 for c in m if a <= c <= b) >= 2:
                sayac[dil] = sayac.get(dil, 0) + 1
                break
    if not sayac:
        return ""
    dil = max(sayac, key=sayac.get)
    return dil if sayac[dil] / len(mesajlar) >= oran else ""


@dataclass
class Spike:
    zaman: float          # patlamanın başladığı an (unix sn)
    tetik: float          # algılandığı an
    puan: float           # pencere puanı
    taban: float          # normal pencere puanı
    kelimeler: list[str] = field(default_factory=list)
    ornek_mesajlar: list[str] = field(default_factory=list)

    @property
    def kat(self) -> float:
        return min(99.0, self.puan / max(self.taban, 1.0))


class SpikeDetector:
    def __init__(self, pencere_sn=10, kat=3.0, en_az_mesaj=25, bekleme_sn=120,
                 isinma_sn=90, taban_sn=300, kova_sn=2.0):
        self.pencere = pencere_sn
        self.kat = kat
        self.en_az = en_az_mesaj
        self.bekleme = bekleme_sn
        self.isinma = isinma_sn
        self.taban_sn = taban_sn
        self.kova = kova_sn
        self._kovalar: dict[int, float] = {}
        self._mesajlar: deque[tuple[float, str, str | None]] = deque()
        self._ilk: float | None = None
        self._son_mesaj: float | None = None
        self._son_spike = -1e18

    def ekle(self, ts: float, text: str) -> None:
        # chat 20 sn'den uzun sustuysa (bağlantı koptu) normal hızı baştan öğren: yanlış "patlama" olmasın
        if self._ilk is None or (self._son_mesaj is not None and ts - self._son_mesaj > 20):
            self._ilk = ts
            self._kovalar.clear()
        self._son_mesaj = ts
        p, kelime = mesaj_puani(text)
        k = int(ts // self.kova)
        self._kovalar[k] = self._kovalar.get(k, 0.0) + p
        self._mesajlar.append((ts, text, kelime))

    def _pencere_puani(self, bitis: float) -> float:
        n = int(round(self.pencere / self.kova))
        son = int(bitis // self.kova)
        return sum(self._kovalar.get(k, 0.0) for k in range(son - n + 1, son + 1))

    def taban(self, simdi: float) -> float:
        """Son birkaç dakikanın tipik (medyan) pencere puanı; şimdiki pencere hariç."""
        n = int(round(self.pencere / self.kova))
        son = int((simdi - self.pencere) // self.kova)
        bas = int((simdi - self.taban_sn) // self.kova)
        if self._ilk is not None:
            bas = max(bas, int(self._ilk // self.kova))
        degerler = []
        for k in range(bas + n - 1, son + 1):
            degerler.append(sum(self._kovalar.get(j, 0.0) for j in range(k - n + 1, k + 1)))
        return statistics.median(degerler) if degerler else 0.0

    def _temizle(self, simdi: float) -> None:
        sinir = simdi - self.taban_sn - self.pencere * 2
        for k in [k for k in self._kovalar if k * self.kova < sinir]:
            del self._kovalar[k]
        while self._mesajlar and self._mesajlar[0][0] < sinir:
            self._mesajlar.popleft()

    def kontrol(self, simdi: float) -> Spike | None:
        self._temizle(simdi)
        if self._ilk is None or simdi - self._ilk < self.isinma:
            return None
        if simdi - self._son_spike < self.bekleme:
            return None
        puan = self._pencere_puani(simdi)
        taban = self.taban(simdi)
        esik = max(self.en_az, taban * self.kat)
        if puan < esik:
            return None
        self._son_spike = simdi
        baslangic = simdi - self.pencere
        pencere_msg = [(t, m, k) for t, m, k in self._mesajlar if t > baslangic]
        sayac = Counter(k for _, _, k in pencere_msg if k)
        ornek = [m for _, m, _ in pencere_msg][-25:]
        return Spike(zaman=baslangic, tetik=simdi, puan=puan, taban=taban,
                     kelimeler=[k for k, _ in sayac.most_common(5)],
                     ornek_mesajlar=ornek)
