using System;
using System.Collections.Generic;

namespace Demo.App;

public interface IWorker
{
    void Run();
}

public class BaseService
{
    public virtual void Run() { }
}

// Single interface in base list (regression: must still count as implements).
public sealed class InterfaceOnlyImpl : IWorker
{
    public void Run() { }
}

public sealed class Worker : BaseService, IWorker
{
    private readonly List<int> _items = new();

    public void DoWork()
    {
        Console.WriteLine("x");
        Run();
    }
}
