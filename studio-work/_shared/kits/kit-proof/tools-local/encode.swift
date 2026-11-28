// usage: swift encode.swift <frames_dir> <out.mp4> [fps] [audio.wav-or-m4a]
import AVFoundation
import AppKit
let a = CommandLine.arguments
let dir = a[1], out = a[2], fps = a.count > 3 ? Int32(a[3])! : 30
let audioPath = a.count > 4 ? a[4] : nil
let files = try FileManager.default.contentsOfDirectory(atPath: dir).filter { $0.hasSuffix(".jpg") }.sorted()
guard let first = NSImage(contentsOfFile: dir + "/" + files[0]), let cg0 = first.cgImage(forProposedRect: nil, context: nil, hints: nil) else { fatalError("no frames") }
let W = cg0.width, H = cg0.height
try? FileManager.default.removeItem(atPath: out)
let w = try AVAssetWriter(outputURL: URL(fileURLWithPath: out), fileType: .mp4)
let vi = AVAssetWriterInput(mediaType: .video, outputSettings: [AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: W, AVVideoHeightKey: H, AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 12_000_000, AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel]])
let ad = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: vi, sourcePixelBufferAttributes: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB, kCVPixelBufferWidthKey as String: W, kCVPixelBufferHeightKey as String: H])
w.add(vi); w.startWriting(); w.startSession(atSourceTime: .zero)
for (i, f) in files.enumerated() {
  while !vi.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.002) }
  guard let img = NSImage(contentsOfFile: dir + "/" + f), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
  var pb: CVPixelBuffer?; CVPixelBufferCreate(nil, W, H, kCVPixelFormatType_32ARGB, nil, &pb)
  CVPixelBufferLockBaseAddress(pb!, [])
  let ctx = CGContext(data: CVPixelBufferGetBaseAddress(pb!), width: W, height: H, bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(pb!), space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue)!
  ctx.draw(cg, in: CGRect(x: 0, y: 0, width: W, height: H)); CVPixelBufferUnlockBaseAddress(pb!, [])
  ad.append(pb!, withPresentationTime: CMTime(value: Int64(i), timescale: fps))
}
vi.markAsFinished()
let sem = DispatchSemaphore(value: 0); w.finishWriting { sem.signal() }; sem.wait()
print("wrote", out, files.count, "frames", w.status.rawValue)
