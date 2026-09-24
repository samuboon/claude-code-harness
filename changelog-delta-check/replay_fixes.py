# -*- coding: utf-8 -*-
"""Replay public commits that fixed a changelog's dates or links: was it flagged before the fix?

    python replay_fixes.py                          # the commits listed below (--half "held out")
    python replay_fixes.py owner/name@SHA ...       # any other public commits
    python replay_fixes.py --search "fix changelog date" [--search ...]   # find candidates
    python replay_fixes.py --search all > cands.jsonl                     # the 18 queries in QUERIES
    python replay_fixes.py --classify cands.jsonl   # keep those whose patch shows a date/version/link fix
    python replay_fixes.py --checker old/changelog_check.py ...          # replay with another version
    python replay_fixes.py --repos [--half "held out"]   # today's changelog of the repositories below
    python replay_fixes.py --show owner/name@SHA    # print the changelog lines the commit changed

For each commit it reads the commit's patch from github.com (`<sha>.patch`), keeps the changelog
files it touches, reads each file at the commit from raw.githubusercontent.com, rebuilds the file
as it was just before by undoing the patch, and runs changelog_check on both, with "today" set to
the commit's own date (so a date that was in the future when it was written is read as such).

A commit is counted only if its patch itself shows the kind of fix this checker is about, read
from the diff alone and before the checker runs:

  date     a release heading kept its version and changed its date
  version  a release heading kept its date and changed its version
  link     a link definition (`[1.2.3]: url`) or a heading's link kept its label and changed its URL

and prints, per commit:

  caught   an error before the fix on a line or version the commit changed, none after
  partly   an error before on what it changed, and still one after
  warned   only a warning before on what it changed
  missed   nothing before on what it changed

Nothing is written to disk and nothing is sent anywhere. The patch and the raw file are not API
calls; --search is one call per query (GitHub allows 10 a minute without a key).
"""
import argparse
import datetime as dt
import email.utils
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changelog_check as t  # noqa: E402

UA = {"User-Agent": "changelog-delta-check-replay"}

# (repository, commit, kind, half) -- the README's replay table. Found with GitHub's commit search
# (the queries in QUERIES), kept only when the patch itself shows a date, version or link fix on a
# release heading, and split in two by commit id before any tuning: every other one held out.
FIXES = [
    ("dustnet-atp/dustnet", "01b7a1684a81", "date", "tune"),
    ("ManpreetS2/StrikeCaller", "0301e69e7343", "date", "held out"),
    ("amr-m-abdelgawad/devctl", "03d8b2209583", "link", "tune"),
    ("vaibhavgupta9877/ruprizzle-orm", "049d8c639546", "link", "held out"),
    ("dgilperez/qlik_elixir", "04ee68918b11", "date", "tune"),
    ("GabrielPabloG/aiosdeck", "05043c2b7867", "link", "held out"),
    ("shakacode/react_on_rails", "078a8b0f414e", "link", "tune"),
    ("yvgude/lean-ctx", "0992cf72cb77", "date", "held out"),
    ("Zious11/wirerust", "0b0af260b89f", "link", "tune"),
    ("gr8it/charts-openshift", "0c31d98ae43c", "date", "held out"),
    ("NovaCode37/Prism-platform", "0e81adb1fe21", "date", "tune"),
    ("jakeryderv/usdata", "0f6ee057f239", "date", "held out"),
    ("leminhtienla/dut_calendar", "0fa90be5ae1d", "link", "tune"),
    ("valentinarodrigues/dummy-release-project", "11d6f79be3cb", "link", "held out"),
    ("emrefirat/release-it-GO", "1282983785ee", "link+version", "tune"),
    ("cotenthusiast/choicebench", "12c3662166cc", "date", "held out"),
    ("KalleL94/Periodical", "131defc25c18", "date", "tune"),
    ("kappy7777/kappastream", "148d4662338a", "link", "held out"),
    ("MattJackson/usagio", "15de04d398e1", "link", "tune"),
    ("hansipie/ecotokens", "16c32a98b9e0", "link", "held out"),
    ("Aiirik/AreaLoot", "16eb6647c62a", "date", "tune"),
    ("langchain-ai/langchain-mongodb", "1816901a7ec3", "date", "held out"),
    ("lazytitan30/billing-doctor", "183188cb1a63", "date", "tune"),
    ("lukasNebr/stream-web-provider", "187ba3a4a809", "date", "held out"),
    ("KeeForge/KeeForge", "1938dd33b95f", "date", "tune"),
    ("brainfoolong/form-data-json", "1a32e12deed9", "date", "held out"),
    ("abdulrhmansaad456eg/SDRS", "1a33d68e88c6", "date", "tune"),
    ("hsl1230/http-forge.cli", "1b6809e0d5cb", "date+version", "held out"),
    ("relytcloud/terraform-provider-relyt", "1b7bee422c5b", "date", "tune"),
    ("WyattAu/auditlog", "1cfba266f5e2", "date", "held out"),
    ("euthm/superretometer", "1d8da528a1ff", "date", "tune"),
    ("fstubner/harness-dispatch", "1edf0ae2b15c", "link", "held out"),
    ("SXKDZ/Stacks", "1f94c8b5bcb8", "link", "tune"),
    ("NikolayDA/picture_helper", "212430520dd0", "link", "held out"),
    ("maik3531/Magnolie-Organizer", "22fcebd07ac6", "date", "tune"),
    ("YawLabs/aws-mcp", "23473b824dea", "link", "held out"),
    ("EstebanForge/pi-extensions", "2418f49ae9ff", "date", "tune"),
    ("liam-i/FlyHUD", "249a25d0efd7", "date+link", "held out"),
    ("the-converter-523/aim-lift-legal", "252131d85c04", "date", "tune"),
    ("OpenRTMP/librtmp2", "253eaf86f1bb", "date", "held out"),
    ("chottodev/mms3", "2676b170fd1c", "link", "tune"),
    ("antirek/chat3", "2676b170fd1c", "link", "held out"),
    ("optiflowic/kumolo", "269babd35666", "link", "tune"),
    ("mudbungie/brazen", "26f0589ad400", "date", "held out"),
    ("Expressive-Tea/green-tea", "270480b2d6e3", "link", "tune"),
    ("natescherer/postmodern-repo-copiertemplate", "285e0c838a72", "version", "held out"),
    ("3aKHP/QuickQuip", "29f14ff7638a", "link", "tune"),
    ("Sevthered/pdf2wiki", "2a7458cc4611", "link", "held out"),
    ("TruePPM/trueppm", "2ac7fa16ed6d", "link", "tune"),
    ("raj921/vulngate", "2ca37b498e48", "version", "held out"),
    ("Lorenzo-Coslado/macos-faceid", "2dd232ea6c9d", "link", "tune"),
    ("meganemura/nukadoko", "2e30f98352c8", "date", "held out"),
    ("doretox/atomicvulns", "2f98f201af03", "link", "tune"),
    ("umbgtt10/crap4rust", "2fdc4e248497", "date", "held out"),
    ("hello-wxs/yezi", "303bf864eb88", "date", "tune"),
    ("imitravanu/anvil", "30cf93a83a15", "link", "held out"),
    ("iot-solutions-ru/ispf", "30e0eefb4a3c", "link", "tune"),
    ("painlessanalytics/datacenter-cloud-ip-lists", "325fa45e786c", "date", "held out"),
    ("gabryxdev/KernelTrace", "33f30760e928", "link", "tune"),
    ("xiaocao666tzh/SZU_WLAN_DupConnect", "36df92533f7a", "date", "held out"),
    ("Danny-de-bree/bound", "37331acedb83", "link", "tune"),
    ("niktimf/field-kinds", "37cfde652c18", "date", "held out"),
    ("aself101/openai-image-api", "3903219be518", "link", "tune"),
    ("vugi99/nanos-lint", "39d05fdae8c0", "date", "held out"),
    ("noahogbi/testimonium", "3ae9bd25aab2", "date", "tune"),
    ("shahram-boshra/MILIA", "3b7d94b14c2f", "date", "held out"),
    ("urbanowiczbartlomiej-hub/OG-E", "3c20a9acae5c", "date", "tune"),
    ("GhostTypes/ff-5mp-hass", "3c369e3f0b68", "date+link", "held out"),
    ("pollybird/zhycms", "3c45f12a1761", "date", "tune"),
    ("Danpc11/LiPNet", "3d5c895b7e35", "date", "held out"),
    ("pander33/SailwindCoop", "3d656a94a505", "date", "tune"),
    ("Aesthetic-Engine/godot-runtime-bridge", "3d943d9919f6", "date", "held out"),
    ("thelazymillennial/ai-agents-it-services", "3e1635e7022d", "date", "tune"),
    ("twist347/terse-dsa", "3f1d2bab3077", "date", "held out"),
    ("NeurodataWithoutBorders/aqnwb", "3f64f8a03edb", "date", "tune"),
    ("qatration/qatration", "4027d2867137", "date", "held out"),
    ("bengizmo/voxint", "4078219879ff", "link", "tune"),
    ("simplynadaf/devpub", "4259d0278661", "date", "held out"),
    ("Schema-Smith/SchemaSmith", "42d2a62d528b", "date", "tune"),
    ("flyingrobots/edict", "431ed87d1a6a", "date+version", "held out"),
    ("oeftimie/vv-claude-harness", "45aaf7383b38", "date", "tune"),
    ("GSI-HPC/slurm-temperature-check", "469aa0bbb0a6", "date", "held out"),
    ("Ziaeemehr/JaxCont", "476f0313f92b", "date", "tune"),
    ("MelAlejandrino/Schlag", "488fe57c434d", "date", "held out"),
    ("unairada/pi-session-profile-selector", "48e38efcff16", "date", "tune"),
    ("nf-core/genomeqc", "492e055220e9", "date", "held out"),
    ("jedarden/AgentScribe", "4933a8f227b1", "link", "tune"),
    ("heru-opensource/flowgraph", "49ebfd842939", "date", "held out"),
    ("jeanlucio/moodle-mod_playercross", "49fb82456dad", "date", "tune"),
    ("ckagias/discord-bot", "4ac55a105d59", "link", "held out"),
    ("hashicorp/terraform-provider-google-beta", "4c207d353d05", "date+version", "tune"),
    ("tedkulp/herdr-kickoff", "4c2c16ac8cc9", "version", "held out"),
    ("rafaelsantana6/zapo-rest", "4c6e686c88a2", "link", "tune"),
    ("drop-project-edu/Drop-Project-for-Intellij-Idea", "4e0948b7c43f", "link", "held out"),
    ("Smartoire/paxaver-mcp", "4e42b4af911b", "date", "tune"),
    ("gellsmore-svg/tirzah", "4eed26d83191", "link", "held out"),
    ("thoscut/YANuget", "4f3e7895a8a6", "date", "tune"),
    ("0xdea/singsing-rs", "501cf4835a2f", "version", "held out"),
    ("AlexWayfer/chatter-labels", "509e0c3765fc", "date", "tune"),
    ("river-creative/populi-api", "51c3e2f6b829", "date", "held out"),
    ("kilerdevs/DeadDropMGMT", "5299191c84e4", "link", "tune"),
    ("leonardomarino/duo_auth", "52a5e22a0473", "date", "held out"),
    ("FlowMatrix-AI/dolibarr-novo-theme", "53150d83fb11", "date", "tune"),
    ("YawLabs/oam", "539fd456d879", "link", "held out"),
    ("turnerrainer/FileFerry", "54074d94952f", "link", "tune"),
    ("hashicorp/terraform-provider-google", "540f8652dfc9", "date+version", "held out"),
    ("chottodev/mms3", "54c64aca7fd7", "link", "tune"),
    ("antirek/chat3", "54c64aca7fd7", "link", "held out"),
    ("nightgauge/nightgauge", "55d2c6e80c8f", "link", "tune"),
    ("rainmanjam/polyemesis", "576f457fd40d", "date", "held out"),
    ("gdesmott/system-deps", "58446bc14b59", "link", "tune"),
    ("kavi936/naturalvoice", "58a160b05e6f", "link", "held out"),
    ("RandyZ/openspec-ext", "5950a995db0a", "link", "tune"),
    ("jolicode/automapper", "5adf927e6bcf", "date", "held out"),
    ("Zi-Yi-Ming/ProjectForge", "5ae4e5619f8f", "date", "tune"),
    ("rafaelsantana6/zapo-rest", "5b1994d5dfc0", "link", "held out"),
    ("MarkusMit/calendar-stats-card", "5ba64a8e1f0e", "link", "tune"),
    ("attevon-llc/OpenTranscribe", "5bb92740dcdb", "date+link", "held out"),
    ("ebbbang/laravel-mailroom", "5ce5000eda65", "date", "tune"),
    ("EnterpriseDB/kubectl-cnp-diagnostic", "5e05a080598a", "date", "held out"),
    ("Di-kairos/paranoid-tools", "5e4ba76b9c86", "link", "tune"),
    ("yafitzdev/fitz-sage", "5ec299ac9b78", "link", "held out"),
    ("gammahazard/groundwork", "5ee05065ec75", "link", "tune"),
    ("Avaray/lora-keywords-finder", "5f40098d17d6", "link", "held out"),
    ("DarkMatterProductions/mcp-project-context-server", "5fea70022ea5", "version", "tune"),
    ("OmneWave/spec-kit-figma-starter", "607be362202e", "date", "held out"),
    ("eddiethedean/moltres", "62bd442c751f", "link", "tune"),
    ("clojure-emacs/clj-suitable", "63342e28f510", "date", "held out"),
    ("diazMelgarejo/Perpetua-Tools", "6454ff5945f3", "date", "tune"),
    ("nguyenquangkhai/cdk-manager", "6547cde57d6a", "date", "held out"),
    ("yabowarcherio/oui-lookup", "65cf644bcb91", "link", "tune"),
    ("arunkumar-mourougappane/argonone-rs", "6664378fdb7e", "link", "held out"),
    ("qnbs/AI-Research-Orchestrator", "68ecb1e5a225", "link", "tune"),
    ("rodme02/xeque-engine", "693a1ff3ea65", "date", "held out"),
    ("k9fr4n/PSWinOps", "6bafe71db617", "date", "tune"),
    ("itk-kimai/AakSamlBundle", "6bbfc0804647", "date+version", "held out"),
    ("thirawat27/Ruvyxa", "6c14cbd5e1d9", "date", "tune"),
    ("worldline/devview", "6ce9a23bd26c", "link", "held out"),
    ("mediusfy/modulex", "6de6bf1f4211", "link", "tune"),
    ("wings1848/dsh-mcp-lazy", "6e741d522ef5", "link", "held out"),
    ("mi-for-the-rust-of-us/anamnesis", "6f7a6cabae67", "date", "tune"),
    ("marpi82/py-bragerone", "6fa7b825b719", "link", "held out"),
    ("NeelFrostrain/UnrealLauncher", "746eea7335c8", "version", "tune"),
    ("danielep71/VBA-DATETIMEPICKER", "75a771f5d578", "date", "held out"),
    ("peczenyj/structalign", "76bbe7593d4a", "link", "tune"),
    ("melody0709/vox_mic", "774d3b34bf4a", "date", "held out"),
    ("derek-rein/exr-converter", "7790593053b6", "link", "tune"),
    ("KOZ39/Knee-Fixer", "790fabe93ed1", "date", "held out"),
    ("lucas-albers-lz4/fwlive", "79b02389b198", "link", "tune"),
    ("KTANE-MODS/DMG-GUI", "7a70e51a096c", "date", "held out"),
    ("the-events-calendar/tribe-common", "7af406dfdc7c", "date", "tune"),
    ("theBraindonor/crypts-and-commits", "7b7facb0a276", "date", "held out"),
    ("mingisrookie/codex-switch", "7d2ed8484d36", "date", "tune"),
    ("zcbacxc/movie-narrator", "81fac55d865a", "link", "held out"),
    ("PsychQuant/ooxml-swift", "83d7dcbbacf9", "date", "tune"),
    ("luanmorenommaciel/agentspec", "83eac83000ec", "date", "held out"),
    ("libraz/libcantus", "8671114c58b4", "link", "tune"),
    ("Botts-Innovative-Research/osh-oakridge-buildnode", "8799f6e8ed50", "date", "held out"),
    ("jeanlucio/moodle-mod_playerwords", "87c81f3124c2", "date", "tune"),
    ("iurFRIEND/openrouter-connector", "87f53c88dab3", "date", "held out"),
    ("SuperMarioYL/agentfuse-sdk", "893746c75653", "link", "tune"),
    ("mycodedoesnotcompile2/arti_mirror", "8a56fda12034", "date", "held out"),
    ("sleepyman1373-mmdvj/arti-c-api", "8a56fda12034", "date", "tune"),
    ("openresearchtools/wildbuzzard-android", "8a56fda12034", "date", "held out"),
    ("LeonMskRu/arti-mirror", "8a56fda12034", "date", "tune"),
    ("gffice/a-git", "8a56fda12034", "date", "held out"),
    ("zydou/arti", "8a56fda12034", "date", "tune"),
    ("leads2b/receita-tools", "8b5f91b788f9", "date", "held out"),
    ("rvdbreemen/adr-kit", "8cd70b895721", "link", "tune"),
    ("Humblemonk/dicemaiden-rs", "8ceb1824ad1d", "date", "held out"),
    ("JuliaManifolds/ManoptExamples.jl", "8db20c6598b9", "date", "tune"),
    ("DaweiTian/SPC-MONITOR", "90059f655b20", "date", "held out"),
    ("jeffersongoncalves/laravel-short-url", "90e870c534db", "link", "tune"),
    ("glatinone/mcpscan", "91683ae5e04f", "link", "held out"),
    ("rangertaha/django-snippets-db", "91719cb92bd2", "link", "tune"),
    ("unbraind/pm-changelog", "91c9ffd8e9be", "date", "held out"),
    ("faustbrian/go-idempotency", "925f834fdbb8", "date", "tune"),
    ("QuantEcon/quantecon-theme.mystmd", "926a3473e7d5", "link", "held out"),
    ("macmixing/keyvox", "92fc3bc7902a", "date", "tune"),
    ("afri-bit/candb-studio", "933b57edb369", "date", "held out"),
    ("yourbourse/trade-server-mcp", "9345737bc8ca", "link", "tune"),
    ("IgnacioGoldchluk/json_path", "93dfcefa9d54", "date", "held out"),
    ("chottodev/mms3", "949e0f3d2aff", "link", "tune"),
    ("antirek/chat3", "949e0f3d2aff", "link", "held out"),
    ("SevWren/Daily-Motivation-Brain-Helper", "951302434760", "date+link", "tune"),
    ("ryanmichaeljames/dataverse-mcp", "9642ce4cc1e1", "link", "held out"),
    ("netresearch/php-ast-edit-skill", "96540bc95c8e", "link", "tune"),
    ("yusif-v/Mimir", "971cbaf4a708", "link", "held out"),
    ("antirek/chat3", "98161550d8ab", "link", "tune"),
    ("youdotcom-oss/youdotcom-python-sdk", "991a0b3e5375", "date", "held out"),
    ("unbraind/pm-changelog", "99d58799f38f", "date", "tune"),
    ("dignite-projects/vault-extract", "99d7a689877b", "link", "held out"),
    ("Revisor01/StatFlow", "9cee2af31f68", "link", "tune"),
    ("sardanioss/httpcloak", "9d05980f6fc5", "date", "held out"),
    ("rudironsoni/specs", "a134415bd5f6", "link", "tune"),
    ("milnet01/OneUp", "a237ce83e2c2", "link", "held out"),
    ("gburd/pg_turbovec", "a60144b44e93", "date", "tune"),
    ("jolt-lang/jolt", "a641de981ca3", "link", "held out"),
    ("yohasebe/rsyntaxtree", "a655ef23adf5", "date", "tune"),
    ("db3-studio/info-guard", "a7776e11a393", "link", "held out"),
    ("aabrur/Rempeyek-Agent-OS", "a7842d68f94a", "date", "tune"),
    ("risk-sentinel/sparc", "a8991ae7e794", "date", "held out"),
    ("AlperenCK/ScopiEngine", "a966768b286c", "link", "tune"),
    ("tabsl/tabslFeedback", "aa881cb923c9", "link", "held out"),
    ("soderlind/cache-tags-for-cloudflare", "aa929ad0eed4", "link", "tune"),
    ("beberlei/metrics", "ab36d8e81993", "date", "held out"),
    ("omniwarp-lab/omniwarp", "ab50d37f1f25", "link", "tune"),
    ("digital-foundry/actualis", "abe756538e21", "date", "held out"),
    ("ericeallen/towel", "ac99e89ea030", "date", "tune"),
    ("atrium-desktop/xdg-desktop-portal-atrium", "acca833dc090", "link", "held out"),
    ("kmoneil/jr", "acdc58bf6d7a", "date", "tune"),
    ("Rouzax/Rename-Domoticz-From-ZwaveJSON", "ae0e1a5408c3", "date", "held out"),
    ("lopatnov/conduit", "af899e593870", "link", "tune"),
    ("Abmstpha/OKAD", "b0d626e2c035", "link", "held out"),
    ("mofluxhq/moflux-bench", "b16a373d0bdf", "date", "tune"),
    ("MahdyNazari/direct-link-resolver", "b3879e893774", "link", "held out"),
    ("Energinet-SimTools/MTB", "b3a7da45da50", "date", "tune"),
    ("rulebeat/rulebeat", "b3cb6052296b", "link", "held out"),
    ("python-cmd2/cmd2", "b4d6cbbc607a", "date", "tune"),
    ("jebakumarj/md-kanban", "b52f099c8d72", "date", "held out"),
    ("jhavl/spatialgeometry", "b5e8049264a7", "date", "tune"),
    ("Yumash/BabelChat", "b877e3fdc58d", "date", "held out"),
    ("iliaal/fastchart", "b8993ddacfd9", "link", "tune"),
    ("Aontaigh/laravel-api-skeleton", "b8db5b252705", "link", "held out"),
    ("ccache/ccache-storage-http-go", "b9177783ab73", "link", "tune"),
    ("duanjiangDJ/ai-model-pricing", "ba445a54e940", "version", "held out"),
    ("internetarchive/heritrix3", "bb0c7e918daf", "date", "tune"),
    ("Chemaclass/unspent", "bd364c8eda32", "link", "held out"),
    ("ImagingDataCommons/libdicom", "bdb851027730", "date", "tune"),
    ("vaibhavgupta9877/ruprizzle-orm", "beac2abc462d", "link", "held out"),
    ("jacking75/JobDispatcherNET", "c01f98626532", "link", "tune"),
    ("dragocz95/elowen-plugins", "c0a281426616", "date", "held out"),
    ("mayankjain1815-commits/n8n", "c0e5a94c5101", "link", "tune"),
    ("LukasLaubert/FerriteSolidMechanics.jl", "c10084c5f09f", "link", "held out"),
    ("chottodev/mms3", "c1abdff0b64c", "link", "tune"),
    ("antirek/chat3", "c1abdff0b64c", "link", "held out"),
    ("juninbr866-beep/VSCodroid", "c1e6026e0c20", "link", "tune"),
    ("rmyndharis/VSCodroid", "c1e6026e0c20", "link", "held out"),
    ("juandresrodca/CompatSentinel", "c2db7d42b401", "date", "tune"),
    ("hansmartensdev/Astro-Rocket", "c42809b0151d", "date", "held out"),
    ("MotherofallVPNs/MoaV", "c8f363a8a750", "link", "tune"),
    ("apairo-robotics/apairo", "ca8a589b9178", "link", "held out"),
    ("spacebub/qzdl", "cc4c6c892a3f", "date", "tune"),
    ("assassinaj602/sate_ai", "cc9873e6c0ef", "link", "held out"),
    ("cognitivegears/ha-escpos-thermal-printer", "cccb688aecd1", "link", "tune"),
    ("locus313/macos-wireless-autoswitch", "ce4cca4379fe", "link", "held out"),
    ("TerraImperfecta/YearFirst", "cf493f7fbc03", "date", "tune"),
    ("Kevin28576/fanuc", "cfdd93a5d56b", "link", "held out"),
    ("ctrondlp/pyguitest", "d0164f2fb873", "link", "tune"),
    ("yo35/kokopu", "d037ee249379", "date", "held out"),
    ("voidmatcha/e2e-skills", "d04884a6cd53", "date", "tune"),
    ("einfachPudi/GuildWeave", "d2231c850ca3", "date", "held out"),
    ("muminkoykiran/safe-tab-url-lister", "d23ba1859023", "date", "tune"),
    ("zenden2k/uptooda", "d3b166a2c818", "date", "held out"),
    ("kylebarron/arro3", "d65a1a5eeee0", "date", "tune"),
    ("EOSC-Data-Commons/matchmaker", "d65aea538735", "date", "held out"),
    ("kameroli/aoss", "d7ea715a66df", "date+link", "tune"),
    ("CePeU/Quick-Journal-Page-Callouts", "d808f8d613a7", "date", "held out"),
    ("jtauschl/openproject-ce-mcp", "d9134046b1d9", "date", "tune"),
    ("petlenz/tmech", "d985bbb7ff7d", "date", "held out"),
    ("DiogoRibeiro7/anomalybench", "d9ed9e70b5ec", "date", "tune"),
    ("wahln/ipax", "da229a289e47", "link", "held out"),
    ("vteial/saranidhi", "da76a6c99640", "link", "tune"),
    ("rust-bitcoin/rust-bitcoin", "da7ae89d5eaf", "link", "held out"),
    ("WindySnowOwl/fractadyne", "dcc0f7adaa25", "date", "tune"),
    ("qnbs/AI-Research-Orchestrator", "dcf4d177c8a5", "link", "held out"),
    ("MCBECD/site", "dd31dcf140a8", "version", "tune"),
    ("curl/curl-container", "dee775cfeff1", "date", "held out"),
    ("chieftools/backupchief-agent", "def8f7ff1edd", "link", "tune"),
    ("musa-labs-indonesia/kiddy-land", "dfad9c1e724e", "link", "held out"),
    ("umbralcalc/stochadex", "dfb6e860563e", "link", "tune"),
    ("Chris-Wolfgang/ETL-Abstractions", "e2fd62cf17e1", "date", "held out"),
    ("iliagerman/joint-bob", "e391b2f6019d", "date", "tune"),
    ("ViSchock66/nisaba-rag", "e4e84a195d1f", "date", "held out"),
    ("Dwade58200/nuvio-configuration", "e5f92f0a7c0b", "date", "tune"),
    ("magiqsoftware/enterprise-frontend-action", "e6f8d6bff37a", "link", "held out"),
    ("umbgtt10/crap4rust", "e720b5ac33e9", "date", "tune"),
    ("xianglun918/scan-lun", "e8002fc1bec2", "link", "held out"),
    ("spenceriam/impulse", "e9a7cd2dece2", "date", "tune"),
    ("mlmr-coder/CodeWhale", "ea1f09f29c2e", "date", "held out"),
    ("Hmbown/Codewhale", "ea1f09f29c2e", "date", "tune"),
    ("ocx-sh/indexbot", "eb9cbf0bd992", "link", "held out"),
    ("ownasquare/cheaper", "ebe63f1b84cd", "date", "tune"),
    ("shellui/website", "ef04a5d03e27", "date", "held out"),
    ("rleeon/hoard", "ef2abeba3f6c", "date", "tune"),
    ("DMJoh/Mediqux", "ef5a04dcd5c7", "date", "held out"),
    ("shi-rudo/result-ts", "ef7e5ad81153", "date", "tune"),
    ("cfpramod/open-museum-mcp", "f049304aad1e", "date", "held out"),
    ("dfa1/rocksdb-ffm", "f1d54396ccaa", "link", "tune"),
    ("MEGWARE-HPC/i18n-sentry", "f509b2aa7632", "date", "held out"),
    ("Bilal-Lodhi/cerberus", "f52fda19e441", "date+link", "tune"),
    ("bari-psy77/serial-hub-monitor", "f6a9adbd815c", "date", "held out"),
    ("andrewkushnerov/gsheets-mcp", "f75021b0c3a8", "date", "tune"),
    ("antithesishq/anta", "f77cad7d67ba", "date", "held out"),
    ("mykolapodpriatov/drupal-ci-templates", "f7ae62f237ed", "link", "tune"),
    ("flyingrobots/wesley", "f84e1d7d5dc1", "link", "held out"),
    ("achird-labs/rift", "f85c07a754d4", "link", "tune"),
    ("davidsneighbour/kollitsch.dev", "f86b5e3bcab8", "link+version", "held out"),
    ("sandro-defender/energy_guard", "f8ffed74129f", "date", "tune"),
    ("bschlaack/Orynivo", "f90098baceda", "date", "held out"),
    ("yasersyed/habit-tracker", "fbcc2454fd43", "link", "tune"),
    ("ecladatta/star-q", "fc3995f2965f", "link", "held out"),
    ("mlavrinenko/outdatty", "fc68216c4a47", "link", "tune"),
    ("psytor/astrogators-shared-ui", "fc7adf68e7d3", "link", "held out"),
    ("adamgreenwell/wayfindr", "fc804c12ddcb", "date", "tune"),
    ("smartscanapp/smartscan-android-lib", "fd01303467c0", "date", "held out"),
    ("rolereactor/bot", "fd05b691819a", "link", "tune"),
    ("Kevin-McIsaac/dsh-workspace-git-badge", "fd94998d6393", "link", "held out"),
    ("chriswayneh/lab-in-a-box", "fd972b9f2838", "link", "tune"),
    ("CertaMesh/gaze", "fdc3be268ad3", "link", "held out"),
    ("plexusone/dashforge", "fe61e95bd3ee", "link", "tune"),
    ("ActiveInferenceInstitute/Generalized_Notation_Notation", "feea1846549f", "link", "held out"),
    ("astrostl/pentameter", "ff3dee0b1860", "date", "tune"),
]

QUERIES = [
    "fix changelog date", "fix date in changelog", "changelog date typo", "correct changelog date",
    "fix release date changelog", "changelog wrong year", "fix changelog year", "fix year in changelog",
    "fix changelog links", "fix compare links changelog", "fix changelog compare link",
    "fix unreleased link", "changelog link typo", "fix changelog version", "changelog version typo",
    "fix version in changelog", "fix changelog release date", "wrong date changelog",
]

# (repository, half) -- well-known repositories with a changelog at the root, split before tuning.
REPOS = [
    ("aio-libs/aiohttp", "tune"),
    ("alacritty/alacritty", "held out"),
    ("Alamofire/Alamofire", "tune"),
    ("angular/angular", "held out"),
    ("astral-sh/ruff", "tune"),
    ("astral-sh/uv", "held out"),
    ("Automattic/mongoose", "tune"),
    ("axios/axios", "held out"),
    ("babel/babel", "tune"),
    ("boto/boto3", "held out"),
    ("BurntSushi/ripgrep", "tune"),
    ("celery/celery", "held out"),
    ("clap-rs/clap", "tune"),
    ("composer/composer", "held out"),
    ("date-fns/date-fns", "tune"),
    ("elixir-lang/elixir", "held out"),
    ("encode/httpx", "tune"),
    ("eslint/eslint", "held out"),
    ("evanw/esbuild", "tune"),
    ("expressjs/express", "held out"),
    ("eza-community/eza", "tune"),
    ("facebook/react", "held out"),
    ("faker-ruby/faker", "tune"),
    ("fastify/fastify", "held out"),
    ("flutter/flutter", "tune"),
    ("gin-gonic/gin", "held out"),
    ("golangci/golangci-lint", "tune"),
    ("google/gson", "held out"),
    ("gradio-app/gradio", "tune"),
    ("grafana/grafana", "held out"),
    ("guzzle/guzzle", "tune"),
    ("hashicorp/consul", "held out"),
    ("hashicorp/nomad", "tune"),
    ("hashicorp/terraform", "held out"),
    ("hashicorp/vault", "tune"),
    ("heartcombo/devise", "held out"),
    ("helix-editor/helix", "tune"),
    ("highlightjs/highlight.js", "held out"),
    ("httpie/cli", "tune"),
    ("hynek/structlog", "held out"),
    ("JakeWharton/timber", "tune"),
    ("jekyll/jekyll", "held out"),
    ("jestjs/jest", "tune"),
    ("jqlang/jq", "held out"),
    ("JuliaLang/julia", "tune"),
    ("junegunn/fzf", "held out"),
    ("jupyterlab/jupyterlab", "tune"),
    ("keepachangelog/keepachangelog", "held out"),
    ("knex/knex", "tune"),
    ("Kotlin/kotlinx.coroutines", "held out"),
    ("laravel/framework", "tune"),
    ("Leaflet/Leaflet", "held out"),
    ("less/less.js", "tune"),
    ("mitmproxy/mitmproxy", "held out"),
    ("mochajs/mocha", "tune"),
    ("moment/moment", "held out"),
    ("nodejs/node", "tune"),
    ("pallets/click", "held out"),
    ("pallets/flask", "tune"),
    ("pallets/jinja", "held out"),
    ("phoenixframework/phoenix", "tune"),
    ("PHPMailer/PHPMailer", "held out"),
    ("pnpm/pnpm", "tune"),
    ("postcss/postcss", "held out"),
    ("prettier/prettier", "tune"),
    ("prometheus/prometheus", "held out"),
    ("psf/black", "tune"),
    ("psf/requests", "held out"),
    ("puma/puma", "tune"),
    ("pydantic/pydantic", "held out"),
    ("pypa/pip", "tune"),
    ("pypa/setuptools", "held out"),
    ("pytest-dev/pytest", "tune"),
    ("python-attrs/attrs", "held out"),
    ("python-poetry/poetry", "tune"),
    ("rack/rack", "held out"),
    ("realm/SwiftLint", "tune"),
    ("remix-run/react-router", "held out"),
    ("rollup/rollup", "tune"),
    ("rubocop/rubocop", "held out"),
    ("rust-lang/cargo", "tune"),
    ("rust-lang/mdBook", "held out"),
    ("rust-lang/rustlings", "tune"),
    ("sass/dart-sass", "held out"),
    ("Seldaek/monolog", "tune"),
    ("sharkdp/bat", "held out"),
    ("sharkdp/fd", "tune"),
    ("sharkdp/hyperfine", "held out"),
    ("sidekiq/sidekiq", "tune"),
    ("sinatra/sinatra", "held out"),
    ("sirupsen/logrus", "tune"),
    ("socketio/socket.io", "held out"),
    ("sqlalchemy/sqlalchemy", "tune"),
    ("square/okhttp", "held out"),
    ("square/retrofit", "tune"),
    ("starship/starship", "held out"),
    ("storybookjs/storybook", "tune"),
    ("tailwindlabs/tailwindcss", "held out"),
    ("Textualize/rich", "tune"),
    ("Textualize/textual", "held out"),
    ("tj/commander.js", "tune"),
    ("tmux/tmux", "held out"),
    ("traefik/traefik", "tune"),
    ("typeorm/typeorm", "held out"),
    ("typescript-eslint/typescript-eslint", "tune"),
    ("uber-go/zap", "held out"),
    ("vitejs/vite", "tune"),
    ("vuejs/core", "held out"),
    ("XAMPPRocky/tokei", "tune"),
    ("yargs/yargs", "held out"),
    ("yarnpkg/berry", "tune"),
    ("zellij-org/zellij", "held out"),
]


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429) and i + 1 < tries:
                time.sleep(20)
                continue
            if i + 1 == tries:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if i + 1 == tries:
                raise
            time.sleep(3)
    return None


def search(query, pages=1):
    out = []
    for page in range(1, pages + 1):
        u = ("https://api.github.com/search/commits?per_page=100&page=%d&q=" % page) + urllib.parse.quote(query)
        req = urllib.request.Request(u, headers=dict(UA, Accept="application/vnd.github+json"))
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (403, 422, 429):
                time.sleep(65)
                with urllib.request.urlopen(req, timeout=40) as r:
                    d = json.load(r)
            else:
                raise
        for it in d.get("items", []):
            if len(it.get("parents", [])) > 1:
                continue            # merge commits: the patch is empty; the fix is in a parent
            out.append((it["repository"]["full_name"], it["sha"], it["commit"]["message"].splitlines()[0]))
        time.sleep(7)
    return out


# ---------------------------------------------------------------- patches

def split_patch(text):
    """Return (date, {path: [hunks]}) for the first commit in a .patch. A hunk is
    (old_start, old_len, new_start, new_len, [lines with their ' ', '-', '+' marks])."""
    date = None
    m = re.search(r"^Date: (.+)$", text, re.M)
    if m:
        try:
            date = email.utils.parsedate_to_datetime(m.group(1).strip()).date()
        except (TypeError, ValueError):
            date = None
    files = {}
    cur = None
    hunk = None
    for ln in text.split("\n"):
        if ln.startswith("diff --git "):
            cur = None
            hunk = None
            continue
        if ln.startswith("+++ "):
            p = ln[4:].strip()
            cur = p[2:] if p.startswith("b/") else (None if p == "/dev/null" else p)
            if cur is not None:
                files.setdefault(cur, [])
            continue
        if ln.startswith("--- "):
            continue
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", ln)
        if m and cur is not None:
            hunk = [int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1), []]
            files[cur].append(hunk)
            continue
        if hunk is not None and ln[:1] in (" ", "-", "+", "\\"):
            if ln.startswith("\\"):
                continue
            hunk[4].append(ln)
        elif ln.startswith("-- ") or ln == "--":
            hunk = None          # the mail signature at the end of a .patch
    return date, files


def undo(after, hunks):
    """Rebuild the file before the commit from the file after it and the commit's hunks."""
    new = after.split("\n")
    out = []
    pos = 0                      # index into new (0-based)
    for os_, ol, ns, nl, body in hunks:
        start = ns - 1 if nl > 0 else ns
        out.extend(new[pos:start])
        for ln in body:
            if ln[:1] in (" ", "-"):
                out.append(ln[1:])
        pos = start + sum(1 for ln in body if ln[:1] in (" ", "+"))
    out.extend(new[pos:])
    return "\n".join(out)


def changed_lines(hunks):
    """(old line numbers removed, new line numbers added, removed texts, added texts)."""
    old, new, rem, add = set(), set(), [], []
    for os_, ol, ns, nl, body in hunks:
        o, n = os_, ns
        for ln in body:
            k = ln[:1]
            if k == " ":
                o += 1
                n += 1
            elif k == "-":
                old.add(o)
                rem.append(ln[1:])
                o += 1
            elif k == "+":
                new.add(n)
                add.append(ln[1:])
                n += 1
    return old, new, rem, add


def heading_facts(line):
    """(version, date text, url) of a release heading line, or None."""
    s = line.strip()
    h = re.match(r"^ {0,3}#{1,6}\s+(.*)$", s)
    txt = h.group(1) if h else (s if re.match(r"^[\[vV]?\d+\.\d+", s) else None)
    if txt is None:
        return None
    e = t.read_entry(0, txt, [txt], {})
    if not e:
        return None
    return e.raw, (e.date_text or e.placeholder or ""), (e.inline_url or "")


def fix_kinds(rem, add):
    """What the diff alone says the commit fixed (before any checker runs)."""
    kinds = set()
    versions = set()
    r_heads = [heading_facts(x) for x in rem]
    a_heads = [heading_facts(x) for x in add]
    r_heads = [x for x in r_heads if x]
    a_heads = [x for x in a_heads if x]
    for rv, rd, ru in r_heads:
        for av, ad, au in a_heads:
            if rv == av and rd != ad and rd and ad:
                kinds.add("date")
                versions.add(rv)
            if rv == av and ru != au and ru and au:
                kinds.add("link")
                versions.add(rv)
            if rv != av and rd == ad and rd:
                kinds.add("version")
                versions.update((rv, av))
    r_defs = {}
    for x in rem:
        m = t.LINKDEF.match(x)
        if m:
            r_defs[m.group(1).strip().lower()] = m.group(2)
    for x in add:
        m = t.LINKDEF.match(x)
        if m:
            lab = m.group(1).strip().lower()
            if lab in r_defs and r_defs[lab] != m.group(2):
                kinds.add("link")
                versions.add(lab)
    return kinds, versions


def adds_release(rem, add):
    """A commit that adds a release also moves the Unreleased link along; that alone is not a fix."""
    r = {h[0] for h in (heading_facts(x) for x in rem) if h}
    a = {h[0] for h in (heading_facts(x) for x in add) if h}
    return sorted(a - r)


def date_changes(rem, add):
    """(version, old date, new date) for each heading whose date the commit changed."""
    out = []
    for x in rem:
        h = heading_facts(x)
        if not h:
            continue
        for y in add:
            g = heading_facts(y)
            if g and g[0] == h[0] and g[1] != h[1]:
                o = t.find_date(h[1])[0] if h[1] else None
                n = t.find_date(g[1])[0] if g[1] else None
                out.append((h[0], o, n))
    return out


def related(f, lines, versions):
    if f.line in lines:
        return True
    return any(re.search(r"(?<![\w.])v?" + re.escape(v) + r"(?![\w.])", f.msg) for v in versions if v)


def replay(repo, sha, checker=t, verbose=False):
    patch = get("https://github.com/%s/commit/%s.patch" % (repo, sha))
    if not patch:
        return {"repo": repo, "sha": sha, "result": "unreadable", "why": "no patch"}
    date, files = split_patch(patch)
    res = {"repo": repo, "sha": sha[:12], "date": date.isoformat() if date else None, "files": []}
    worst = None
    order = ["caught", "partly", "warned", "missed"]
    kinds_all = set()
    for path, hunks in files.items():
        if not t.NAMES.match(path.rsplit("/", 1)[-1]):
            continue
        old, new, rem, add = changed_lines(hunks)
        kinds, versions = fix_kinds(rem, add)
        if not kinds:
            continue
        after = get("https://raw.githubusercontent.com/%s/%s/%s" % (repo, sha, urllib.parse.quote(path)))
        if after is None:
            continue
        before = undo(after, hunks)
        fb, sb, eb = checker.check_text(path, before, date)
        fa, sa, ea = checker.check_text(path, after, date)
        eb_rel = [f for f in fb if f.level == "error" and related(f, old, versions)]
        wb_rel = [f for f in fb if f.level == "warning" and related(f, old, versions)]
        ea_rel = [f for f in fa if f.level == "error" and related(f, new, versions)]
        if eb_rel and not ea_rel:
            r = "caught"
        elif eb_rel:
            r = "partly"
        elif wb_rel:
            r = "warned"
        else:
            r = "missed"
        kinds_all |= kinds
        other_b = [f for f in fb if f not in eb_rel and f not in wb_rel]
        new_a = [f for f in fa if f.level == "error" and f not in ea_rel and
                 not any(o.code == f.code and o.msg == f.msg for o in fb)]
        res["files"].append({"path": path, "kinds": sorted(kinds), "versions": sorted(versions),
                             "result": r, "before": [str(f) for f in eb_rel + wb_rel],
                             "after": [str(f) for f in ea_rel],
                             "other_before": [str(f) for f in other_b],
                             "new_after": [str(f) for f in new_a],
                             "entries": len(eb),
                             "adds_release": adds_release(rem, add),
                             "date_changes": [[v, o.isoformat() if o else None, n.isoformat() if n else None]
                                              for v, o, n in date_changes(rem, add)]})
        if worst is None or order.index(r) < order.index(worst):
            worst = r
    res["result"] = worst or "not a fix of this kind"
    res["kinds"] = sorted(kinds_all)
    return res


def show(repo, sha):
    patch = get("https://github.com/%s/commit/%s.patch" % (repo, sha))
    date, files = split_patch(patch or "")
    print("%s@%s %s" % (repo, sha[:12], date))
    for path, hunks in files.items():
        if not t.NAMES.match(path.rsplit("/", 1)[-1]):
            continue
        old, new, rem, add = changed_lines(hunks)
        print(" ", path, fix_kinds(rem, add))
        for x in rem[:12]:
            print("   -", x[:160])
        for x in add[:12]:
            print("   +", x[:160])


def classify(repo, sha):
    """The kinds of fix the patch alone shows, per changelog file (no checker runs)."""
    patch = get("https://github.com/%s/commit/%s.patch" % (repo, sha))
    if not patch:
        return None
    date, files = split_patch(patch)
    kinds, versions = set(), set()
    for path, hunks in files.items():
        if not t.NAMES.match(path.rsplit("/", 1)[-1]):
            continue
        old, new, rem, add = changed_lines(hunks)
        k, v = fix_kinds(rem, add)
        kinds |= k
        versions |= v
    return sorted(kinds), sorted(versions), (date.isoformat() if date else None)


def classify_file(path, workers=8):
    """Read candidates (the JSON lines --search prints) and print the ones whose patch shows a fix."""
    from concurrent.futures import ThreadPoolExecutor
    cands = []
    seen = set()
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            d = json.loads(ln)
            if (d["repo"], d["sha"]) not in seen:
                seen.add((d["repo"], d["sha"]))
                cands.append(d)

    def one(d):
        try:
            return d, classify(d["repo"], d["sha"])
        except Exception as ex:          # an unreadable patch is left out and counted
            return d, ("error", repr(ex)[:80])

    n_fix = n_err = 0
    with ThreadPoolExecutor(workers) as ex:
        for d, r in ex.map(one, cands):
            if r is None or r[0] == "error":
                n_err += 1
                continue
            if r[0]:
                n_fix += 1
                print(json.dumps({"repo": d["repo"], "sha": d["sha"], "kinds": r[0], "versions": r[1],
                                  "date": r[2], "msg": d.get("msg")}, ensure_ascii=False))
                sys.stdout.flush()
    print("# %d candidates, %d show a fix in the patch, %d unreadable" % (len(cands), n_fix, n_err), file=sys.stderr)


def run_repos(repos, checker=t, as_of=None):
    out = []
    for repo in repos:
        found = None
        for name in ("CHANGELOG.md", "CHANGES.md", "HISTORY.md", "NEWS.md", "History.md", "Changes.md",
                     "Changelog.md", "changelog.md", "CHANGELOG.rst", "CHANGES.rst", "HISTORY.rst", "NEWS.rst",
                     "Changelog.rst", "History.markdown", "CHANGELOG.markdown", "CHANGELOG", "CHANGES", "NEWS",
                     "RELEASES.md", "CHANGELOG.txt", "CHANGES.txt"):
            txt = get("https://raw.githubusercontent.com/%s/HEAD/%s" % (repo, name))
            if txt:
                found = (name, txt)
                break
        if not found:
            out.append({"repo": repo, "file": None})
            continue
        f, st, entries = checker.check_text(found[0], found[1], as_of)
        out.append({"repo": repo, "file": found[0], "entries": len(entries), "stats": st,
                    "findings": [str(x) for x in f]})
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("commits", nargs="*", help="owner/name@SHA")
    ap.add_argument("--half", help='only the commits (or repositories) in this half: "tune" or "held out"')
    ap.add_argument("--search", action="append", help="a commit-search query (repeatable); 'all' = QUERIES")
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--repos", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--checker", help="path to another changelog_check.py (to replay an earlier version)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--classify", help="a file of --search output: keep the commits whose patch shows a fix")
    a = ap.parse_args(argv)
    checker = t
    if a.checker:
        import importlib.util
        spec = importlib.util.spec_from_file_location("checker_alt", a.checker)
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)

    if a.classify:
        classify_file(a.classify)
        return 0
    if a.search:
        qs = QUERIES if a.search == ["all"] else a.search
        seen = set()
        for q in qs:
            for repo, sha, msg in search(q, a.pages):
                if (repo, sha) in seen:
                    continue
                seen.add((repo, sha))
                print(json.dumps({"repo": repo, "sha": sha, "msg": msg, "query": q}, ensure_ascii=False))
                sys.stdout.flush()
        return 0
    if a.repos:
        rs = [r for r, h in REPOS if not a.half or h == a.half]
        res = run_repos(rs, checker, dt.date.today())
        for r in res:
            print(json.dumps(r, ensure_ascii=False) if a.json else
                  "%s %s %s" % (r["repo"], r.get("file"), "; ".join(r.get("findings", [])[:8])))
        return 0
    if a.show:
        for c in a.commits:
            repo, sha = c.split("@")
            show(repo, sha)
        return 0
    todo = [tuple(c.split("@")) for c in a.commits] or [(r, s) for r, s, k, h in FIXES if not a.half or h == a.half]
    tally = {}
    for repo, sha in todo:
        try:
            r = replay(repo, sha, checker)
        except Exception as ex:          # one unreadable commit does not stop the table
            r = {"repo": repo, "sha": sha[:12], "result": "unreadable", "why": repr(ex)[:120]}
        tally[r["result"]] = tally.get(r["result"], 0) + 1
        if a.json:
            print(json.dumps(r, ensure_ascii=False))
        else:
            print("%-8s %s@%s %s" % (r["result"], r["repo"], r["sha"], ",".join(r.get("kinds", []))))
            for fl in r.get("files", []):
                for x in fl["before"][:3]:
                    print("    before: " + x)
                for x in fl["after"][:3]:
                    print("    after:  " + x)
        sys.stdout.flush()
    if not a.json:
        print("; ".join("%s %d" % kv for kv in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
