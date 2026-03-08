project('aside', 'c',
  version: '0.2.0',
  default_options: ['c_std=c11', 'warning_level=2'],
  meson_version: '>= 0.64',
)

py = import('python').find_installation(pure: false)

py.install_sources(
  'aside/__init__.py',
  'aside/cli.py',
  'aside/config.py',
  'aside/daemon.py',
  'aside/keyring.py',
  'aside/models.py',
  'aside/plugins.py',
  'aside/query.py',
  'aside/sentence_buffer.py',
  'aside/state.py',
  'aside/status.py',
  'aside/tts.py',
  preserve_path: true,
)

py.install_sources(
  'aside/reply/__init__.py',
  'aside/reply/window.py',
  preserve_path: true,
)

py.install_sources(
  'aside/input/__init__.py',
  'aside/input/window.py',
  preserve_path: true,
)

py.install_sources(
  'aside/tools/__init__.py',
  'aside/tools/memory.py',
  preserve_path: true,
)

py.install_sources(
  'aside/overlay/__init__.py',
  'aside/overlay/accent_bar.py',
  'aside/overlay/css.py',
  'aside/overlay/markdown.py',
  'aside/overlay/message_view.py',
  'aside/overlay/conversation.py',
  'aside/overlay/picker.py',
  'aside/overlay/reply_input.py',
  'aside/overlay/window.py',
  'aside/overlay/app.py',
  preserve_path: true,
)

py.install_sources(
  'aside/voice/__init__.py',
  'aside/voice/audio.py',
  'aside/voice/listener.py',
  'aside/voice/speech_detector.py',
  'aside/voice/stt.py',
  preserve_path: true,
)

subdir('overlay')
