"""Verify all modules import correctly."""
import sys
sys.path.insert(0, '.')

modules = {
    "ai.viral_detector": ["ViralMoment", "DetectionResult", "detect_viral_moments", "generate_viral_score"],
    "ai.title_generator": ["GeneratedTitle", "TitleGenerationResult", "generate_titles", "generate_hashtags", "generate_hook", "generate_pinned_comment"],
    "ai.emoji_engine": ["add_emojis_to_text", "get_emoji_for_word", "get_emojis_for_topic", "batch_add_emojis"],
    "ai.groq_client": [],
    "transcription.extractor": ["AudioExtractor", "extract_audio", "normalise_audio", "split_audio"],
    "transcription.whisper": ["WordTimestamp", "SentenceTimestamp", "Transcript", "TranscriptionResult", "transcribe_with_groq", "transcribe_full_video"],
    "video_processing.downloader": ["DownloadResult", "DownloadProgress", "VideoDownloader", "download_youtube_video", "get_video_info"],
    "video_processing.clipping": ["ClipResult", "VideoClipper", "clip_video", "remove_silence_from_clip", "clip_multiple"],
    "video_processing.reframe": ["ReframeResult", "VideoReframer", "reframe_to_vertical"],
    "video_processing.output": ["OutputResult", "VideoOutputRenderer", "generate_final_output", "generate_thumbnail"],
    "video_processing.broll": ["BrollClip", "BrollPlacement", "BrollEngine", "generate_broll"],
    "captions.generator": ["CaptionFrame", "CaptionGenerator", "generate_caption_frames", "generate_srt_from_words"],
    "opencv_utils.face_tracker": ["FaceTracker", "KalmanFilter2D", "detect_faces", "track_speaker", "calculate_crop_region", "detect_faces_in_video"],
    "opencv_utils.motion_detector": ["MotionFrame", "MotionAnalysis", "MotionDetector", "detect_scene_change", "calculate_camera_movement", "get_zoom_points", "detect_scene_changes"],
    "ffmpeg_utils.processor": ["FFmpegProcessor", "SilenceSegment", "SceneSegment"],
    "pipeline.processor": ["PipelineProcessor", "PipelineConfig", "PipelineStage", "PipelineStatus", "PipelineProgress", "PipelineResult", "process_viral_short"],
}

all_ok = True
for module_name, expected_names in modules.items():
    try:
        mod = __import__(module_name, fromlist=expected_names)
        for name in expected_names:
            if not hasattr(mod, name):
                print(f"  MISSING: {module_name}.{name}")
                all_ok = False
        print(f"  OK: {module_name} ({len(expected_names)} symbols)")
    except ImportError as e:
        print(f"  FAIL: {module_name} — {e}")
        all_ok = False

print()
if all_ok:
    print("All Part 2 modules verified successfully!")
else:
    print("Some modules have issues — see above.")
    sys.exit(1)
