# References

## Ceph and storage systems
- Sage A. Weil, Scott A. Brandt, Ethan L. Miller, Darrell D. E. Long, Carlos Maltzahn. "Ceph: A Scalable, High-Performance Distributed File System." OSDI 2006 (USENIX). https://www.usenix.org/conference/osdi-06/ceph-scalable-high-performance-distributed-file-system
- Sage A. Weil, Scott A. Brandt, Ethan L. Miller, Carlos Maltzahn. "CRUSH: Controlled, Scalable, Decentralized Placement of Replicated Data." SC 2006. https://ieeexplore.ieee.org/document/4090205/
- Ajay Gulati, Arif Merchant, Peter J. Varman. "mClock: Handling Throughput Variability for Hypervisor IO Scheduling." OSDI 2010 (USENIX). https://www.usenix.org/conference/osdi10/mclock-handling-throughput-variability-hypervisor-io-scheduling
- Ceph documentation: configuration management and runtime config set. https://docs.ceph.com/en/quincy/rados/configuration/ceph-conf/

## Failure detectors and adaptive detection
- Naohiro Hayashibara, Xavier Defago, Rami Yared, Takuya Katayama. "The Phi Accrual Failure Detector." SRDS 2004. DOI:10.1109/RELDIS.2004.1353004 https://dblp.org/rec/conf/srds/HayashibaraDYK04
- Marin Bertier, Olivier Marin, Pierre Sens. "Implementation and Performance Evaluation of an Adaptable Failure Detector." DSN 2002. https://dblp.org/rec/conf/dsn/BertierMS02
- Wei Chen, Sam Toueg, Marcos K. Aguilera. "On the Quality of Service of Failure Detectors." IEEE Transactions on Computers 51(5), 2002. https://www.microsoft.com/en-us/research/publication/quality-service-failure-detectors/
- Abhinandan Das, Indranil Gupta, Ashish Motivala. "SWIM: Scalable Weakly-consistent Infection-style Process Group Membership Protocol." DSN 2002. https://www.cs.cornell.edu/projects/quicksilver/public_pdfs/SWIM.pdf
- Armon Dadgar, James Phillips, Jon Currey. "Lifeguard: Local Health Awareness for More Accurate Failure Detection." arXiv 2017 (NSDI 2018). https://arxiv.org/abs/1707.00788
- Tushar Deepak Chandra, Sam Toueg. "Unreliable Failure Detectors for Reliable Distributed Systems." JACM 43(2), 1996. https://dblp.org/rec/journals/jacm/ChandraT96
- Mikel Larrea, Antonio Fernández, Sergio Arévalo. "Optimal Implementation of the Weakest Failure Detector for Solving Consensus." SRDS 2000. https://www.dsc.ufcg.edu.br/~fubica/papers/FD/LFA.pdf

## Foundational theory (consensus and failure detection)
- Michael J. Fischer, Nancy A. Lynch, Michael S. Paterson. "Impossibility of Distributed Consensus with One Faulty Process." JACM 32(2), 1985. https://www.sigmod.org/publications/dblp/db/journals/jacm/FischerLP85.html
- Danny Dolev, Cynthia Dwork, Larry Stockmeyer. "On the Minimal Synchronism Needed for Distributed Consensus." JACM 34, 1987. https://research.ibm.com/publications/on-the-minimal-synchronism-needed-for-distributed-consensus
- Marcos K. Aguilera, Wei Chen, Sam Toueg. "Using the Heartbeat Failure Detector for Quiescent Reliable Communication and Consensus in Partitionable Networks." Theoretical Computer Science 220(1), 1999. https://www.sciencedirect.com/science/article/pii/S0304397598002357
- Rachid Guerraoui, Mikel Larrea, André Schiper. "Non-Blocking Atomic Commitment with an Unreliable Failure Detector." SRDS 1995. https://infoscience.epfl.ch/entities/publication/07eda305-0053-4888-9857-3ca813c330d4
- Paulo Veríssimo, António Casimiro, Christof Fetzer. "The Timely Computing Base: Timely Actions in the Presence of Uncertain Timeliness." DSN 2000. https://repositorio.ulisboa.pt/entities/publication/29067d01-db7a-4e67-87bf-0f2f2d961d3f
- Danny Dolev, Roy Friedman, Idit Keidar, Dahlia Malkhi. "Failure Detectors in Omission Failure Environments." PODC 1997. https://dblp.org/db/conf/podc/podc97
