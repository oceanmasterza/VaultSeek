"""Local discovery must preserve secrets, URL bases and missing-install isolation."""

from vaultseek.services.local_setup import LocalSetupService


def service(tmp_path, *, port_probe=None):
    return LocalSetupService(
        roaming=tmp_path,
        local=tmp_path,
        program_data=tmp_path,
        port_probe=port_probe or (lambda _host, _port: False),
    )


def write(tmp_path, name, text):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_detect_custom_ports_and_secrets(tmp_path):
    write(
        tmp_path,
        "Prowlarr/config.xml",
        "<Config><Port>9697</Port><UrlBase>/index</UrlBase><ApiKey>secret</ApiKey></Config>",
    )
    write(
        tmp_path,
        "sabnzbd/sabnzbd.ini",
        "[misc]\nport = 8090\nurl_base = /sabnzbd\napi_key = sab-secret\n"
        "[categories]\n[[music]]\ndir = complete\n",
    )
    write(
        tmp_path,
        "qBittorrent/qBittorrent.ini",
        "[Preferences]\nWebUI\\Enabled=true\nWebUI\\Port=8085\n"
        "WebUI\\Username=listener\nWebUI\\Password_PBKDF2=secret-hash\n",
    )
    results = service(tmp_path).discover()
    assert results[0].values == {"url": "http://127.0.0.1:9697/index", "key": "secret"}
    assert results[1].values == {"url": "http://127.0.0.1:8085", "username": "listener"}
    assert results[2].values == {"url": "http://127.0.0.1:8090/sabnzbd", "key": "sab-secret"}
    assert "secret" not in repr(results)


def test_missing_malformed_and_disabled_are_nonfatal(tmp_path):
    write(tmp_path, "Prowlarr/config.xml", "<broken")
    path = write(tmp_path, "qBittorrent/qBittorrent.ini", "[Preferences]\nWebUI\\Enabled=false")
    before = path.read_bytes()
    results = service(tmp_path).discover()
    assert all(not row.values for row in results)
    assert "Enable" in results[1].note
    assert path.read_bytes() == before


def test_https_and_quoted_sab_values(tmp_path):
    write(
        tmp_path,
        "sabnzbd/sabnzbd.ini",
        '[misc]\nenable_https=1\nhttps_port=9090\nurl_base="/sab"\napi_key="test"',
    )
    assert service(tmp_path).discover()[2].values["url"] == "https://127.0.0.1:9090/sab"


def test_missing_section_is_reported(tmp_path):
    write(tmp_path, "sabnzbd/sabnzbd.ini", "[other]\nport=12")
    assert not service(tmp_path).discover()[2].values


def test_sab_configobj_global_keys_and_nested_sections(tmp_path):
    write(
        tmp_path,
        "sabnzbd/sabnzbd.ini",
        "config_version=19\n[misc]\nport=8090\napi_key=secret\nurl_base=/sabnzbd\n"
        "[servers]\n[[news.example]]\nport=563",
    )
    item = service(tmp_path).discover()[2]
    assert item.values["url"] == "http://127.0.0.1:8090/sabnzbd"


def test_sab_vaultseek_category_and_qbit_save_path(tmp_path):
    write(
        tmp_path,
        "sabnzbd/sabnzbd.ini",
        "[misc]\nport=8090\napi_key=secret\n[categories]\n[[vaultseek]]\ndir=complete\n",
    )
    write(
        tmp_path,
        "qBittorrent/qBittorrent.ini",
        "[Preferences]\nWebUI\\Enabled=true\nWebUI\\Port=8085\n"
        "WebUI\\Username=listener\nDownloads\\SavePath=D:\\\\Downloads\\qbit\n",
    )
    results = service(tmp_path).discover()
    assert results[1].values["save_path"].endswith("qbit")
    assert results[2].values["category"] == "vaultseek"
    assert "secret" not in results[2].field_summary()
    assert "API key found" in results[2].field_summary()


def test_nicotine_preserves_bound_host_and_masks_token(tmp_path):
    write(
        tmp_path,
        "nicotine/config/config",
        "[plugins]\nenabled=['api-nicotine-plus-main']\n"
        "api-nicotine-plus-main={'host':'192.168.1.2','port':12339,'api_token':'hidden'}",
    )
    item = service(tmp_path).discover()[3]
    assert item.values["host"] == "192.168.1.2"
    assert item.values["api_token"] == "hidden"
    assert "hidden" not in repr(item)


def test_jellyfin_preserves_url_prefix(tmp_path):
    write(
        tmp_path,
        "Jellyfin/Server/config/network.xml",
        "<NetworkConfiguration><InternalHttpPort>8097</InternalHttpPort>"
        "<BaseUrl>/music</BaseUrl></NetworkConfiguration>",
    )
    assert service(tmp_path).discover()[4].values["url"] == "http://127.0.0.1:8097/music"


def test_navidrome_and_listening_note(tmp_path):
    write(tmp_path, "Navidrome/navidrome.toml", "Port = 4534\nAddress = '0.0.0.0'\n")
    results = service(tmp_path, port_probe=lambda host, port: port == 4534).discover()
    navidrome = results[5]
    assert navidrome.values["url"] == "http://127.0.0.1:4534"
    assert navidrome.listening is True
    missing_plex = results[6]
    assert not missing_plex.values
    assert "manual" in missing_plex.note.lower()


def test_sab_roaming_fallback(tmp_path):
    write(
        tmp_path,
        "sabnzbd/sabnzbd.ini",
        "[misc]\nport=8088\napi_key=from-roaming\n",
    )
    item = service(tmp_path).discover()[2]
    assert item.values["url"] == "http://127.0.0.1:8088"
    assert item.values["key"] == "from-roaming"
