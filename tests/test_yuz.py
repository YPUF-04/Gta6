from klipci.yuz import facecam_sec


def test_sabit_yuz_facecam_olur():
    w, h = 960, 540
    # sol altta sabit facecam yüzü + her karede farklı yerde oyun yüzü
    kutular = [[(60 + (i % 2), 380, 50, 50), (100 + i * 60, 100, 30, 30)] for i in range(12)]
    fc = facecam_sec(kutular, w, h)
    assert fc is not None
    x, y, fw, fh = fc
    assert x < 0.15 and y > 0.4 and 0 < fw <= 1 and 0 < fh <= 1
    assert x + fw <= 1.0001 and y + fh <= 1.0001


def test_yuz_yoksa_none():
    assert facecam_sec([[] for _ in range(10)], 960, 540) is None


def test_nadir_yuz_none():
    kutular = [[] for _ in range(10)]
    kutular[3] = [(100, 100, 60, 60)]
    assert facecam_sec(kutular, 960, 540) is None


def test_pip_duzeni_render(tmp_path):
    import subprocess
    from klipci.kurgu import ass_yaz, dikey_video, video_saglam_mi
    src = tmp_path / "s.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=3", "-f", "lavfi", "-i",
                    "sine=d=3", "-shortest", str(src)], check=True)
    ass = tmp_path / "a" / "yazi.ass"
    ass.parent.mkdir()
    ass_yaz(ass, 3, "", "🎥 twitch.tv/x", "@ben", [(0.2, 2, "just accept it")], [], "pip", None, (1, "chat koptu"))
    out = tmp_path / "o.mp4"
    dikey_video(src, 0, 3, out, ass, 1.3, (0, 0, 0.3, 0.3), 1.0, False, "pip")
    assert video_saglam_mi(out, en_az_sn=2)
