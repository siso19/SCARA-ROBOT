"""
Protocol Maker
프로토콜 제작 및 관리 애플리케이션 진입점
"""

import sys
import os
import faulthandler
import logging
from logging.handlers import RotatingFileHandler

# UTF-8 인코딩 강제 설정 (Docker 환경에서 한글 출력을 위해)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 로그 디렉토리 생성 (도커 환경과 로컬 환경 모두 지원)
# 도커 환경: /app/logs, 로컬 환경: 프로젝트 루트/logs
if os.path.exists("/app"):
    log_dir = "/app/logs"  # 도커 환경
else:
    # 로컬 개발 환경: 프로젝트 루트의 logs 디렉토리 사용
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

# 로그 디렉토리 생성 및 권한 확인
log_file_enabled = False
try:
    os.makedirs(log_dir, exist_ok=True)
    # 쓰기 권한 확인
    if os.access(log_dir, os.W_OK):
        # 테스트 파일 쓰기 시도
        test_file = os.path.join(log_dir, '.write_test')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            log_file_enabled = True
        except (PermissionError, OSError):
            pass
except (PermissionError, OSError):
    pass

if not log_file_enabled:
    print(f"⚠️ [WARNING] 로그 디렉토리에 쓰기 권한이 없습니다: {log_dir}")
    print(f"   로그는 콘솔에만 출력됩니다. 파일 저장은 비활성화됩니다.")
    print(f"   해결 방법: sudo chown -R $USER:$USER {log_dir}")

# 로깅 설정 (권한이 있을 때만 FileHandler 추가)
# 시간대 설정 (한국 시간대 사용)
import time
import datetime
class KSTFormatter(logging.Formatter):
    """한국 시간대(KST, UTC+9)를 사용하는 Formatter"""
    def formatTime(self, record, datefmt=None):
        # UTC 시간을 KST로 변환 (UTC+9)
        utc_time = datetime.datetime.utcfromtimestamp(record.created)
        kst_time = utc_time + datetime.timedelta(hours=9)
        if datefmt:
            return kst_time.strftime(datefmt)
        return kst_time.strftime('%Y-%m-%d %H:%M:%S')

# 루트 로거 설정 (한 번만)
if not logging.root.handlers:
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file_enabled:
        try:
            file_handler = RotatingFileHandler(
                os.path.join(log_dir, 'protocol_maker.log'),
                maxBytes=5 * 1024 * 1024,  # 5MB
                backupCount=5,  # 최대 5개 백업 파일 (총 25MB)
                encoding='utf-8'
            )
            file_handler.setFormatter(KSTFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', '%Y-%m-%d %H:%M:%S'))
            handlers.append(file_handler)
        except (PermissionError, OSError) as e:
            print(f"⚠️ [WARNING] 로그 파일 핸들러 생성 실패: {e}")
    
    # 루트 로거에 핸들러 추가
    for handler in handlers:
        handler.setFormatter(KSTFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', '%Y-%m-%d %H:%M:%S'))
        logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)

# segfault 발생 시 스택 트레이스 출력
faulthandler.enable()
try:
    crash_log_file = open("crash.log", "w", buffering=1)
    faulthandler.enable(file=crash_log_file, all_threads=True)
    sys._crash_log_file = crash_log_file
except Exception as e:
    print(f"⚠️ [DEBUG] faulthandler 파일 출력 설정 실패: {e}")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

from gui.main_window import ProtocolMakerWindow

def cleanup_data_files_on_startup():
    """애플리케이션 시작 시 큰 데이터 파일들을 자동으로 정리"""
    try:
        # utils 모듈 경로 추가
        project_root = os.path.dirname(os.path.abspath(__file__))
        utils_path = os.path.join(project_root, 'utils')
        if utils_path not in sys.path:
            sys.path.insert(0, utils_path)
        
        from cleanup_data_files import cleanup_files
        
        # 백그라운드에서 조용히 정리 (10MB 이상, 24시간 이상 된 파일만)
        results = cleanup_files(
            dry_run=False,
            min_size_mb=10.0,
            max_age_seconds=24 * 60 * 60  # 24시간
        )
        
        if results['deleted'] > 0:
            logging.info(f"🧹 시작 시 데이터 파일 정리 완료: {results['deleted']}개 파일 삭제, {results['total_size_freed_mb']:.1f}MB 확보")
        else:
            logging.debug("🧹 시작 시 데이터 파일 정리: 정리할 파일 없음")
            
    except ImportError:
        # cleanup_data_files 모듈이 없으면 무시
        pass
    except Exception as e:
        # 정리 실패해도 애플리케이션은 계속 실행
        logging.warning(f"⚠️ 데이터 파일 정리 중 오류 (무시): {e}")

def main():
    """메인 함수"""
    # 화면 배율 설정
    os.environ['QT_SCALE_FACTOR'] = '0.8'
    os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '0'
    
    # 네이티브 터미널(X11 세션)에서 segfault 방지를 위한 Qt 환경 변수 설정
    # 원격 터미널(tty 세션)과 동일한 안정성 확보
    xdg_session_type = os.environ.get('XDG_SESSION_TYPE', '').lower()
    is_native_x11 = xdg_session_type == 'x11'
    
    if 'DISPLAY' not in os.environ:
        # DISPLAY가 없으면 offscreen 플랫폼 사용 (백그라운드 실행 시)
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    else:
        # DISPLAY가 있으면 xcb 플랫폼 명시적 설정
        if xdg_session_type == 'wayland':
            # Wayland 환경에서는 xcb 사용 (XWayland)
            os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
        else:
            # X11 환경에서는 xcb 명시적 설정
            os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
    
    # 네이티브 X11 세션에서 segfault 방지를 위한 특별 설정
    if is_native_x11:
        print("🔍 [DEBUG] 네이티브 X11 세션 감지 - 추가 안정화 설정 적용")
        # X11 이벤트 처리 안정화
        os.environ.setdefault('QT_X11_NO_MITSHM', '1')  # X11 공유 메모리 비활성화
        os.environ.setdefault('QT_XCB_GL_INTEGRATION', 'none')  # OpenGL 통합 비활성화 (segfault 방지)
        # X11 동기화 비활성화 (이벤트 루프 충돌 방지)
        os.environ.setdefault('QT_XCB_NATIVE_PAINTING', '0')  # 네이티브 페인팅 비활성화
        # Qt 이벤트 루프 안정성 향상
        os.environ.setdefault('QT_LOGGING_RULES', 'qt.qpa.xcb.*=false')  # X11 관련 로그 최소화
    
    # OpenGL 관련 안정성 향상 (네이티브 터미널에서 segfault 방지)
    # 주석 처리: 소프트웨어 렌더링은 성능 저하가 있으므로 필요시만 활성화
    # os.environ.setdefault('QT_OPENGL', 'software')
    # os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE', '1')
    
    # Qt 이벤트 루프 안정성 향상 (공통)
    os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '0')  # HighDPI 관련 문제 방지
    os.environ.setdefault('QT_SCALE_FACTOR_ROUNDING_POLICY', 'Round')
    
    # Qt 로깅 설정 (X11 세션이 아닌 경우에만 기본값 설정)
    if not is_native_x11 and 'QT_LOGGING_RULES' not in os.environ:
        # segfault 관련 경고만 출력 (너무 많은 로그 방지)
        os.environ['QT_LOGGING_RULES'] = 'qt.qpa.*=false;qt.core.*=false'
    
    # GUI 전용 모드 확인
    gui_only_mode = os.environ.get('GUI_ONLY_MODE', '').lower() in ('1', 'true', 'yes')
    if gui_only_mode:
        print("=" * 80)
        print("🎨 GUI 전용 모드 활성화")
        print("   하드웨어 초기화 없이 GUI만 실행됩니다.")
        print("   이 모드를 비활성화하려면: unset GUI_ONLY_MODE")
        print("=" * 80)
    
    # 디버깅 정보 출력
    print(f"🔍 [DEBUG] Qt 환경 설정:")
    print(f"  - DISPLAY: {os.environ.get('DISPLAY', 'NOT SET')}")
    print(f"  - QT_QPA_PLATFORM: {os.environ.get('QT_QPA_PLATFORM', 'default')}")
    print(f"  - XDG_SESSION_TYPE: {os.environ.get('XDG_SESSION_TYPE', 'NOT SET')} {'(네이티브 X11)' if is_native_x11 else ''}")
    print(f"  - GUI_ONLY_MODE: {os.environ.get('GUI_ONLY_MODE', 'NOT SET')} {'(활성화됨)' if gui_only_mode else ''}")
    print(f"  - QT_X11_NO_MITSHM: {os.environ.get('QT_X11_NO_MITSHM', 'NOT SET')}")
    print(f"  - QT_XCB_GL_INTEGRATION: {os.environ.get('QT_XCB_GL_INTEGRATION', 'NOT SET')}")
    print(f"  - QT_XCB_NATIVE_PAINTING: {os.environ.get('QT_XCB_NATIVE_PAINTING', 'NOT SET')}")
    
    # 시작 시 큰 데이터 파일들 자동 정리
    cleanup_data_files_on_startup()
    
    try:
        app = QApplication(sys.argv)
        app.setStyle('Fusion')
        
        # 네이티브 X11 세션에서 추가 안정화 설정
        if is_native_x11:
            # QApplication 속성 설정으로 X11 이벤트 처리 안정화
            try:
                from PySide6.QtCore import Qt
                # 이벤트 루프 안정성 향상
                app.setAttribute(Qt.ApplicationAttribute.AA_DisableWindowContextHelpButton, True)
                # HighDPI 관련 비활성화 (X11 세션에서 segfault 방지)
                app.setAttribute(Qt.ApplicationAttribute.AA_DisableHighDpiScaling, True)
            except Exception as e:
                print(f"⚠️ [DEBUG] QApplication 속성 설정 중 오류 (무시): {e}")
        
        # Qt 플랫폼 정보 출력
        from PySide6.QtGui import QGuiApplication
        platform_name = QGuiApplication.platformName()
        print(f"  - 실제 사용된 Qt 플랫폼: {platform_name}")
        
        # Protocol Maker 생성
        protocol_maker = ProtocolMakerWindow()
        protocol_maker.show()
        
        # 네이티브 X11 세션에서 segfault 방지: app.exec() 전 QTimer.singleShot 사용 안 함
        # QTimer.singleShot이 포커스 변경 시 segfault 유발 가능
        # X11 세션에서는 processEvents도 최소화
        if is_native_x11:
            # QTimer.singleShot 사용 안 함 (segfault 방지)
            # processEvents도 최소화 (이벤트 루프 충돌 방지)
            pass
        else:
            # X11 세션이 아닌 경우에만 사용
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: None)  # 이벤트 루프 안정화
            QApplication.processEvents()
        
        # app.exec() 실행 (X11 세션에서 segfault 발생 가능 지점)
        try:
            exit_code = app.exec()
            
            # app.exec() 종료 후 최소한의 정리 (segfault 방지)
            # 주의: app.exec() 종료 후에는 Qt 이벤트 루프가 이미 종료된 상태이므로
            # Qt 객체를 정리하는 것은 위험할 수 있습니다.
            # 대신 closeEvent에서 이미 정리되었을 것이므로, 여기서는 최소한의 정리만 수행
            print("🔍 [DEBUG] 애플리케이션 종료 - exit_code:", exit_code)
            
            sys.exit(exit_code)
        except Exception as e:
            print(f"❌ [DEBUG] app.exec() 실행 중 오류: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    except Exception as e:
        print(f"❌ [DEBUG] QApplication 초기화 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main() 