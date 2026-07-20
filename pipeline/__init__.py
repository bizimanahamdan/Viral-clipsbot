"""
Pipeline — End-to-end video processing pipeline for the Viral Shorts Bot.

Orchestrates the entire flow from input to final output:
download → extract audio → transcribe → detect viral moments → clip →
reframe → add captions → add emoji → add zoom → add B-roll → render output
"""

from pipeline.processor import PipelineProcessor

__all__ = ["PipelineProcessor"]
