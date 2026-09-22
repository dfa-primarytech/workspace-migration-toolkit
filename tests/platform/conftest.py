import zipfile

import pytest
from workspace_toolkit.package import CONTENT_NS, MAIN_MIME, REL_NS
from workspace_toolkit.pptx import NS


def fixture_parts():
    return {
        "[Content_Types].xml": f'''<Types xmlns="{CONTENT_NS}"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="png" ContentType="image/png"/><Default Extension="mp4" ContentType="video/mp4"/><Default Extension="wav" ContentType="audio/wav"/><Override PartName="/ppt/presentation.xml" ContentType="{MAIN_MIME}"/></Types>''',
        "_rels/.rels": f'<Relationships xmlns="{REL_NS}"><Relationship Id="root" Type="{NS["r"]}/officeDocument" Target="ppt/presentation.xml"/></Relationships>',
        "ppt/presentation.xml": f'<p:presentation xmlns:p="{NS["p"]}" xmlns:r="{NS["r"]}"><p:sldIdLst><p:sldId id="256" r:id="second"/><p:sldId id="257" r:id="first"/></p:sldIdLst><p:sldSz cx="10668000" cy="7556500"/></p:presentation>',
        "ppt/_rels/presentation.xml.rels": f'<Relationships xmlns="{REL_NS}"><Relationship Id="first" Type="{NS["r"]}/slide" Target="slides/slide1.xml"/><Relationship Id="second" Type="{NS["r"]}/slide" Target="slides/slide2.xml"/></Relationships>',
        "ppt/slides/slide2.xml": f'''<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}"><p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvSpPr txBox="1"/></p:nvSpPr><p:spPr><a:xfrm rot="5400000"><a:off x="12700" y="25400"/><a:ext cx="127000" cy="254000"/></a:xfrm></p:spPr><p:txBody><a:p><a:r><a:rPr b="1"><a:latin typeface="Calibri"/></a:rPr><a:t>Hello school</a:t></a:r></a:p></p:txBody></p:sp><p:pic><p:blipFill><a:blip r:embed="image"/></p:blipFill><p:nvPicPr><p:nvPr><a:videoFile r:link="movie"/></p:nvPr></p:nvPicPr></p:pic><p:futureObject/></p:spTree></p:cSld><p:transition/><p:timing/></p:sld>''',
        "ppt/slides/slide1.xml": f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Last slide</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>',
        "ppt/slides/_rels/slide2.xml.rels": f'<Relationships xmlns="{REL_NS}"><Relationship Id="image" Type="{NS["r"]}/image" Target="../media/image.png"/><Relationship Id="movie" Type="{NS["r"]}/video" Target="../media/video.mp4"/><Relationship Id="audio" Type="{NS["r"]}/audio" Target="../media/audio.wav"/><Relationship Id="url" Type="{NS["r"]}/hyperlink" Target="https://example.invalid/private" TargetMode="External"/></Relationships>',
        "ppt/media/image.png": b"\x89PNG\r\n\x1a\nfixture-image",
        "ppt/media/copy.png": b"\x89PNG\r\n\x1a\nfixture-image",
        "ppt/media/video.mp4": b"\x00\x00\x00\x18ftypmp42fixture-video",
        "ppt/media/audio.wav": b"RIFF\x00\x00\x00\x00WAVEfixture-audio",
        "ppt/theme/theme1.xml": f'<a:theme xmlns:a="{NS["a"]}"><a:themeElements><a:fontScheme><a:majorFont><a:latin typeface="Aptos"/></a:majorFont></a:fontScheme></a:themeElements></a:theme>',
    }


def write_pptx(path, parts=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in (parts or fixture_parts()).items():
            archive.writestr(name, content)
    return path


@pytest.fixture
def pptx(tmp_path):
    return write_pptx(tmp_path / "sample.pptx")
