# SCARA-ROBOT
Hitbot SCARA 로봇팔을 활용한 실험실 워크플로우 자동화 서버입니다.
MEA, TIP, SOURCE, JIG 타겟에 대한 프로토콜 설계, 명령 변환, 로봇 실행, 액체 자동 처리를 지원합니다.

# Overview
이 저장소는 MEA (Microelectrode Array) 바이오센서 실험 자동화를 위한 서버 아키텍처를 담고 있습니다.
사용자가 정의한 실험 프로토콜을 순차적인 로봇 동작 명령으로 변환하여,
표면 기능화, 세균 샘플 처리, PBS 세척, 전기화학 측정(CV/EIS)을 완전 자동으로 실행합니다.

# Architecture
서버는 MVC (Model-View-Controller) 패턴을 기반으로 구성되어 있습니다.

# Command
서버는 프로토콜을 구조화된 JSON 명령 목록(`cmd_list.json`)으로 변환합니다.
각 명령은 로봇 인터페이스 함수와 직접 매핑됩니다.

# Config
로봇 동작은 두 개의 설정 파일로 정의됩니다.
