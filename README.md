# 나만의빛

Lightroom의 라이브러리 / 현상 흐름을 참고한 로컬 사진 편집 프로그램입니다. 네이티브 창 안에서 동작하는 데스크톱 앱이며, 현상은 같은 프로세스 안의 Python 서버가 담당합니다. 사진을 외부 서비스로 전송하지 않습니다.

## 실행

배포본을 설치했다면 macOS는 응용 프로그램의 **나만의빛**, Windows는 시작 메뉴의 **나만의빛**을 실행합니다.

소스에서 바로 실행하려면 Python 3.12와 uv가 필요합니다.

```sh
uv venv --python 3.12
uv pip install -r requirements.lock.txt -r requirements.build.txt
.venv/bin/python desktop.py
```

창 없이 브라우저에서 쓰고 싶으면 `./start.command`를 실행하고 http://127.0.0.1:8000 에 접속합니다. 종료는 터미널에서 Ctrl+C입니다.

```sh
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

## 프로그램 빌드

두 형식 모두 **해당 운영체제에서만** 빌드할 수 있습니다. rawpy(LibRaw), numpy, scipy가 네이티브 확장이라 크로스 컴파일이 되지 않습니다.

### macOS — `.dmg`

```sh
./build_mac.sh
```

`dist/나만의빛.app`과 `dist/나만의빛-1.0.0.dmg`가 만들어집니다. 애드혹 서명만 하므로 Apple Developer ID로 공증한 배포본이 아닙니다. 다른 Mac에서 처음 열 때 Gatekeeper가 막으면 앱을 **우클릭 → 열기**로 한 번 실행하거나 아래 명령으로 격리 속성을 지웁니다.

```sh
xattr -dr com.apple.quarantine /Applications/나만의빛.app
```

### Windows — `.exe`

Windows에서 PowerShell로 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File build_win.ps1
```

`dist\나만의빛\나만의빛.exe`와 배포용 zip이 만들어집니다. [Inno Setup](https://jrsoftware.org/isdl.php)의 `iscc`가 PATH에 있으면 `dist\나만의빛-1.0.0-setup.exe` 설치 프로그램까지 함께 만듭니다. 창은 Edge WebView2 런타임을 사용하며 Windows 11과 최신 Windows 10에는 기본 포함되어 있습니다. 없는 경우 [WebView2 런타임](https://developer.microsoft.com/microsoft-edge/webview2/)을 설치해야 합니다.

아이콘은 `assets/make_icons.py`가 코드로 그려 `.icns`, `.ico`, 파비콘을 생성하며 빌드 스크립트가 자동으로 호출합니다.

macOS 번들 안의 실행 파일만 `Contents/MacOS/Namanuibit`로 둡니다. `CFBundleExecutable`이 ASCII가 아니면 `codesign`이 번들 리소스를 봉인하지 않고 실행 파일만 서명해 검증이 실패합니다. Finder와 메뉴 막대에 보이는 이름은 `나만의빛.app`과 `CFBundleName`이 결정하므로 표시 이름은 그대로 한글입니다. Windows에는 이 제약이 없어 `나만의빛.exe`로 나갑니다.

빌드 파일 이름(`lightloom.spec`, `packaging/lightloom.iss`), 환경 변수 `LIGHTLOOM_DATA` / `LIGHTLOOM_PORT` / `LIGHTLOOM_DEBUG`, 번들 식별자 `com.namanuibit.studio`도 ASCII로 유지합니다. 도구와 셸이 다루는 값이라 한글로 두면 환경에 따라 깨질 수 있습니다.

## 기능

- 여러 사진 가져오기와 드래그 앤 드롭, 라이브러리와 필름 스트립
- LibRaw/rawpy로 CR2, CR3, NEF, NRW, ARW, DNG, RAF, ORF, RW2, PEF, SRW, RAW 디코딩 (실제 지원은 카메라 모델에 따라 다름)
- JPEG, PNG, TIFF, WebP 입력, EXIF 방향 적용과 ICC → sRGB 변환
- 노출, 대비, 하이라이트/섀도, 흰색/검정, 색온도/색조, 생동감/채도, 부분 대비, 선명도, 비네팅, 흑백
- HSL 8색상 × 색상·채도·명도, RGB 및 R/G/B 포인트 커브 (점 추가·이동·삭제, 좌표 입력)와 커브 채도 반영
- 파라메트릭 커브 4구간 및 구간 경계, 섀도/미드톤/하이라이트/글로벌 컬러 그레이딩, 혼합·균형
- 텍스처, 안개 제거, 그레인 양·크기·거칠기, 비네팅 스타일·중간점·원형률·페더·명부 보호
- 선명도 반경·세부·가장자리 마스킹, 휘도·색상 노이즈 감소와 세부 보존
- RGB 원색 보정, 섀도 틴트, 보라·초록 프린지 제거와 색상 범위
- 보정 검색, XMP 적용 내역 (지원/비활성/관리용/미지원/잘못된 값 구분)
- 90도 회전과 **중앙 기준** 비율 자르기 (1:1, 4:3, 3:2, 16:9)
- 6개 기본 프리셋과 XMP 가져오기 / 한 번 클릭해 적용
- 보정 전후 비교, 실행 취소 / 다시 실행, 자동 저장, RGB 히스토그램
- 화면 맞춤 / 25–400% 확대와 드래그 패닝, ⌘ 스크롤 확대
- 원본 크기 또는 축소 JPEG / PNG / TIFF 출력, JPEG 품질 설정, sRGB ICC 포함
- 데스크톱 앱에서는 네이티브 저장 대화상자로 위치를 고르고, 저장 후 폴더에서 바로 확인
- 창 메뉴(사진 / 보정)와 단축키, 편집이 남아 있는 보정 패널 표시

## 보관 위치

`<보관 폴더>/<사진 ID>/`에 원본 사본, 미리보기, 썸네일, 보정값 JSON을 보관합니다. 원래 파일은 수정하지 않습니다.

| 실행 형태 | 보관 폴더 |
| --- | --- |
| 소스 실행 | 프로젝트 안의 `data/` |
| macOS 앱 | `~/Library/Application Support/나만의빛/library` |
| Windows 앱 | `%LOCALAPPDATA%\나만의빛\library` |

`LIGHTLOOM_DATA` 환경 변수로 폴더를 바꿀 수 있습니다. 데스크톱 앱에서는 메뉴 **사진 → 라이브러리 폴더 열기**로 바로 열 수 있습니다. 가져온 프리셋은 창의 localStorage에 저장되며 이 저장소는 `나만의빛/webview` 아래에 유지됩니다. 실행 취소 기록은 현재 사진 편집 세션에만 유지됩니다.

## XMP 호환 범위 및 한계

기본 보정 외에 위에 나열한 HSL, 커브, 그레이딩, 디테일 및 효과 설정을 Camera Raw XMP에서 가져옵니다. 속성 및 요소 표기를 지원하며, 톤 커브의 RDF 포인트 목록도 읽습니다. 실제 매핑과 범위는 `adjustments.py`, `xmp.py`를 참고하세요.

**이전 버전에서 가져온 프리셋은 XMP를 다시 가져와야 새 항목이 적용됩니다.** 과거 저장된 프리셋에는 당시 읽지 못한 값이나 XMP 원문이 없습니다. 같은 이름으로 가져오면 기존 프리셋을 대체합니다. 기존 사진과 보정값은 유지되며 새 항목은 중립 기본값을 사용합니다.

XMP 내부의 `Look` 같은 중첩 리소스는 주 설정과 분리합니다. `Cluster`, `ShowInPresets` 등은 관리 정보로, 0/False/빈 목록 등은 비활성 항목으로 분류합니다. 활성화된 미지원 효과가 있으면 “일부 적용”으로 표시하며, 적용 내역에서 계속 확인할 수 있습니다. 잘못된 커브/범위는 건너뛰고 표시합니다.

**Adobe 엔진의 동일 재현은 아닙니다.** HSL은 색상 구간 보간, 커브는 선형 포인트 보간, 텍스처/부분 대비/선명도는 휘도 다중 스케일 처리, 안개 제거는 다크 채널 기반, 노이즈 감소는 가장자리 보존 가우시안 혼합을 사용합니다. AI 노이즈 제거가 아닙니다. 색온도·원색 보정·컬러 그레이딩·프린지의 XMP 값은 독자 알고리즘으로 근사 적용합니다. 프린지는 선택한 색상과 가장자리의 채도를 줄이며 기하학적 색수차 자동 보정과 다릅니다. 그레인은 고정 시드로 재현할 수 있습니다.

Adobe 프로필/LUT (`Look`, `CameraProfile`, RGB Tables), 프로필 기반 자동 렌즈 보정/자동 색수차, Point Colors/Color Variance, 로컬 마스크, AI 기능은 아직 지원하지 않습니다. 활성 값은 미지원 효과로 표시합니다. 파노라마/HDR 병합, 자유 영역 크롭, 일괄 내보내기도 미구현입니다.

RAW는 16비트 디코딩 후 float32로 보정합니다. 미리보기는 최대 1,600px의 8비트 프록시이며 내보내기는 원본을 다시 디코딩합니다. 출력은 **8비트 RGB**입니다. 고해상도 원본은 메모리와 처리 시간이 더 필요합니다. EXIF/GPS는 출력에 복사하지 않습니다. 파일당 최대 250MB입니다.

## 검증

```sh
uv pip install pytest httpx
.venv/bin/python -m pytest -q
```

자동 검증: 입력/저장/세 가지 출력 형식, 데스크톱 저장 경로 처리와 패키징된 앱의 보관 폴더, 각 신규 보정 및 세부 설정의 픽셀 변화, HSL 선택성·색공간 왕복, 노이즈 감소, 그레인 재현성, 극단값, XMP 커브·중첩 Look 분리·경고 분류, 잘못된 값 검증, RAW 디코딩 옵션. 프런트엔드 DOM 검증에는 커브 편집과 실행 취소, 보정 검색과 빈 검색 결과, 확대/맞춤 전환, 네이티브 저장 대화상자를 거치는 내보내기, 프리셋 및 자동 저장이 포함됩니다.

```sh
npm install --prefix /tmp/lightloom-testdeps jsdom
NODE_PATH=/tmp/lightloom-testdeps/node_modules node tests/frontend.cjs
```
실제 Canon 40D sRAW 샘플을 LibRaw로 디코딩해 보정된 JPEG 원본 크기로 출력하는 통합 검증도 수행했습니다.

기술 자료: [rawpy Params](https://letmaik.github.io/rawpy/api/rawpy.Params.html), [Adobe Camera Raw XMP namespace](https://developer.adobe.com/xmp/docs/xmp-namespaces/crs/). 실제 RAW 검증용 샘플은 [rawpy 테스트 자료](https://github.com/letmaik/rawpy/tree/main/test)를 사용했으며 프로젝트에 포함하지 않습니다.
