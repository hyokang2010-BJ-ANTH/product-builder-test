# afs3d — AFS 촬영 사진 → 3D 두상 모델 → 탈모 면적 정량화 (프로토타입)

AFS 장비로 각도별 촬영한 100여 장의 사진에서 mm 단위 3D 두상 메쉬를 만들고,
두피 노출(탈모) 면적·비율, 이식 밀도별 필요 모낭수, 정수리 지도를 산출합니다.

설계 배경·절차·검증 계획·규제 검토는 **[concept.md](concept.md)** 를 보세요.

> ⚠️ 이 저장소는 공개 상태입니다. **환자 사진·메쉬·리포트를 커밋하지 마세요.**
> `afs3d/work*/`, `afs3d/data/`, `afs3d/demo_data/` 는 `.gitignore` 로 제외되어 있습니다.
> 결과는 연구·상담 보조용이며 의료기기 측정값이 아닙니다.

## 설치

```bash
cd afs3d
pip install -r requirements.txt
sudo apt install colmap        # CPU 빌드: 포즈(sparse)까지. 메쉬(dense)는 CUDA 빌드 COLMAP 필요
```

## 사용

```bash
# 합성 두상 100컷 생성 (환자 사진 없이 시험)
python -m afs3d demo --out demo_data

# 품질 점검 → work/quality.csv
python -m afs3d check --images demo_data/images --out demo_data/work

# 전체 실행: 전처리 → COLMAP → (--dense 시) 메쉬 → 분석
python -m afs3d run --images demo_data/images --work demo_data/work --mask --dense

# 단계별 실행
python -m afs3d prep        --images <사진폴더> --work work --mask
python -m afs3d reconstruct --images <사진폴더> --work work --rig-radius-mm 450 [--mode rig] [--dense]
python -m afs3d analyze     --work work                     # reconstruction.json 의 메쉬·스케일·방향 사용
python -m afs3d analyze     --mesh other.ply --scale 1 --up 0 0 1 --out result   # 외부 메쉬
```

사진 폴더 옆에 `manifest.csv`(filename, azimuth_deg, elevation_deg, radius_mm, focal_px, exposure)가 있으면
자동으로 읽습니다. 형식은 concept.md 2장.

결과 보기: `viewer/index.html` 을 브라우저로 열고 `analysis/coverage.ply` 를 끌어다 놓습니다
(파일은 업로드되지 않고 브라우저 안에서만 열립니다). 로컬 파일로 열 때 CDN 모듈 로딩이 막히면
`python -m http.server -d viewer` 로 띄워 `http://localhost:8000` 에서 여세요.

## 테스트

```bash
python -m pytest -q tests                  # 빠른 테스트 (수 초)
AFS3D_SLOW=1 python -m pytest -q tests     # COLMAP 으로 합성 100컷 실제 재구성 (CPU 수십 분)
```
