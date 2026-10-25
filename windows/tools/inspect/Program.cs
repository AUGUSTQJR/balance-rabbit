using System;
using System.IO;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;

foreach (var path in args)
{
    Console.WriteLine("== " + Path.GetFileName(path) + " (" + new FileInfo(path).Length + " bytes)");
    using var fs = File.OpenRead(path);
    using var pe = new PEReader(fs);
    if (!pe.HasMetadata) { Console.WriteLine("  no metadata"); continue; }
    var md = pe.GetMetadataReader();
    foreach (var handle in md.ManifestResources)
    {
        var res = md.GetManifestResource(handle);
        var name = md.GetString(res.Name);
        long size = 0;
        if (res.Implementation.IsNil)
        {
            var dir = pe.PEHeaders.CorHeader.ResourcesDirectory;
            var off = dir.RelativeVirtualAddress;
            var block = pe.GetSectionData(off);
            var reader = block.GetReader();
            reader.Offset = (int)res.Offset;
            size = reader.ReadInt32();
        }
        Console.WriteLine("  resource " + name + " -> " + size + " bytes");
    }
    foreach (var h in md.AssemblyReferences)
    {
        var a = md.GetAssemblyReference(h);
        Console.WriteLine("  ref " + md.GetString(a.Name) + " " + a.Version);
    }
}
